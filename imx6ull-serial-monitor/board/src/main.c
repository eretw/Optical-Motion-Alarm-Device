#define _POSIX_C_SOURCE 200809L
#include "monitor.h"
#include "protocol.h"
#include <termios.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <signal.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <time.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <inttypes.h>
#include <stdatomic.h>
#define QUEUE_CAP 32   // 内存报警队列最多容纳 32 条事件
#if ATOMIC_INT_LOCK_FREE != 2
#error This program requires lock-free atomic int for its signal/worker stop flag
#endif
static atomic_int stopping; // 两个线程共同使用的退出标志,采用原子类型，避免两个线程并发访问普通变量产生数据竞争
static struct {
    pthread_mutex_t mu; // 	保护共享数据的互斥锁
    struct config cfg; // 采样周期、光照阈值、运动阈值
    struct sample latest, events[QUEUE_CAP]; //最近一次采样结果,报警事件的环形队列
	/*
	*head 队列中最早事件的位置
	*count 当前队列中的事件数量
	*overruns 队列满时丢弃事件的次数
	*errors 传感器采样失败次数
	*generation 采样更新计数，用于判断有没有新数据
	*/
    unsigned head,count,overruns,errors,generation;
    int silence,active;// 当前是否处于消音状态;	当前是否满足超限条件
    struct sensors hw;
} shared={
	.mu=PTHREAD_MUTEX_INITIALIZER,
	.cfg={200,3000,4000} // 采样周期：200 ms;光照阈值：3000;运动阈值：4000
};
static void on_signal(int sig) { (void)sig;stopping=1; }
// 创建采样线程
static void *sample_worker(void *arg)
{
    (void)arg;
    while(!stopping) {
        struct sample s;
		struct config c;
		int alarm,previous,key;
		uint64_t next;
		
        pthread_mutex_lock(&shared.mu);
		c=shared.cfg;
		pthread_mutex_unlock(&shared.mu);
		
        next=now_ms()+c.period_ms;
		sensors_read(&shared.hw,&s);
		key=sensors_key(&shared.hw);
        pthread_mutex_lock(&shared.mu);
		
        previous=shared.active;
        if(s.valid) 
			shared.active=(s.als>(int)c.light_raw || s.motion>(int)c.motion_raw);
        else shared.errors++;
        if(!shared.active)shared.silence=0;
        if(key)shared.silence=1;
        alarm=shared.active&&!shared.silence;s.alarm=alarm;
        if(s.valid&&shared.active&&!previous) {
            if(shared.count<QUEUE_CAP) { shared.events[(shared.head+shared.count)%QUEUE_CAP]=s;shared.count++; }
            else shared.overruns++;
        }
        shared.latest=s;shared.generation++;
        pthread_mutex_unlock(&shared.mu);sensors_alarm(&shared.hw,alarm);
        while(!stopping && now_ms()<next) { struct timespec t={0,20000000};nanosleep(&t,NULL); }
    }
    return NULL;
}
static int send_text(int fd,unsigned type,unsigned seq,const char *s)
{ uint8_t b[MON_FRAME_MAX];size_t n=mon_encode(b,(uint8_t)type,(uint16_t)seq,s,strlen(s));return n?write_deadline(fd,b,n,300):-1; }
static int reply(int fd,const struct mon_frame *f,int ok,const char *msg)
{ char b[160];snprintf(b,sizeof(b),"{\"ok\":%s,\"command\":%u,\"message\":\"%s\"}",ok?"true":"false",f->type,msg);return send_text(fd,MON_REPLY,f->seq,b); }
// 取出报警事件
static int pop_event(struct sample *s)
{
    int found=0;
	pthread_mutex_lock(&shared.mu);
    if(shared.count){
		*s=shared.events[shared.head];
		shared.head=(shared.head+1)%QUEUE_CAP;
		shared.count--;
		found=1;
		}
    pthread_mutex_unlock(&shared.mu);return found;
}
static void usage(void)
{ fprintf(stderr,"monitor --serial /dev/ttymxc0 --state /var/lib/serial-monitor [--mock] [--key /dev/input/eventN]\n"); }

int main(int argc,char **argv)
{
    const char *port=NULL,*dir="/var/lib/serial-monitor",*key=NULL;
	int mock=0,fd=-1,lockfd=-1,i,rc=1;
    struct termios saved;
	pthread_t thread;
	int started=0;
	struct mon_parser parser={0};
    uint64_t boot=0,last_rx=0,last_byte=0,last_event=0;
	unsigned event_seq=0,wire_seq=0,last_gen=0,cursor=0;
    unsigned storage_errors=0,tx_errors=0;
	int connected=0;
	char path[512],json[MON_PAYLOAD_MAX+1];
    for(i=1;i<argc;i++) {
        if(!strcmp(argv[i],"--mock"))mock=1;
        else if(!strcmp(argv[i],"--serial")&&i+1<argc)port=argv[++i];
        else if(!strcmp(argv[i],"--state")&&i+1<argc)dir=argv[++i];
        else if(!strcmp(argv[i],"--key")&&i+1<argc)key=argv[++i];
        else {usage();return 2;}
    }
    if(!port||strlen(dir)>350){usage();return 2;}
    if(mkdir(dir,0700)&&errno!=EEXIST){perror("state directory");return 1;}
    snprintf(path,sizeof(path),"%s/lock",dir);lockfd=open(path,O_CREAT|O_RDWR,0600);
    if(lockfd<0||flock(lockfd,LOCK_EX|LOCK_NB)){perror("another monitor or state lock");goto cleanup;}
    i=config_load(dir,&shared.cfg);
    if(i<0){fprintf(stderr,"Invalid/unreadable config; inspect %s/config (not overwritten).\n",dir);goto cleanup;}
    if(config_save(dir,&shared.cfg)){perror("state durability check");goto cleanup;}
    { int randomfd=open("/dev/urandom",O_RDONLY);ssize_t n=randomfd<0?-1:read(randomfd,&boot,sizeof(boot));
      if(randomfd>=0)close(randomfd);if(n!=sizeof(boot)){fprintf(stderr,"Cannot obtain unique boot id\n");goto cleanup;} }
    if(sensors_open(&shared.hw,mock,key)){perror("sensor/input device");goto cleanup;}
    fd=serial_open(port,&saved);if(fd<0){perror("serial_open");sensors_close(&shared.hw);goto cleanup;}
    signal(SIGINT,on_signal);signal(SIGTERM,on_signal);signal(SIGPIPE,SIG_IGN);
    i=pthread_create(&thread,NULL,sample_worker,NULL);if(i){errno=i;perror("pthread_create");goto finish;}
    started=1;rc=0;fprintf(stderr,"monitor started: %s, 115200 8N1, %s backend\n",port,mock?"MOCK":"HARDWARE");
    while(!stopping) {
        struct pollfd pf={fd,POLLIN,0};int pr=poll(&pf,1,25);struct sample s;unsigned gen,drops,errs;
        if(pr<0&&errno!=EINTR){perror("poll");rc=1;break;}
        if(pr>0&&(pf.revents&(POLLHUP|POLLERR|POLLNVAL))){fprintf(stderr,"Serial endpoint closed\n");rc=1;break;}
        if(parser.used && now_ms()-last_byte>1000)mon_expire(&parser);
        if(pr>0&&(pf.revents&POLLIN)) {
            uint8_t b[256];ssize_t n=read(fd,b,sizeof(b));ssize_t j;
            if(n<0&&errno!=EAGAIN&&errno!=EINTR){perror("serial read");rc=1;break;}
            if(n>0)last_byte=now_ms();
            for(j=0;j<n;j++) { struct mon_frame f;int ok=1;const char *msg="ok";
                if(!mon_feed(&parser,b[j],&f))continue;
                last_rx=now_ms();
                if(memchr(f.payload,0,f.len)){reply(fd,&f,0,"embedded NUL");continue;}
                switch(f.type) {
                case MON_HELLO:connected=1;last_gen=0;msg=mock?"monitor/1 mock":"monitor/1 hardware";break;
                case MON_CONFIG: {
                    struct config c;
                    if(config_parse((char*)f.payload,&c)){ok=0;msg="expected period_ms,light_raw,motion_raw";}
                    else if(config_save(dir,&c)){ok=0;msg="persist failed";storage_errors++;}
                    else {pthread_mutex_lock(&shared.mu);shared.cfg=c;pthread_mutex_unlock(&shared.mu);}
                    break; }
                case MON_SILENCE:pthread_mutex_lock(&shared.mu);shared.silence=1;pthread_mutex_unlock(&shared.mu);break;
                case MON_STOP:stopping=1;msg="returning to terminal";break;
                case MON_EVENT_ACK:if(event_ack(dir,(char*)f.payload)){ok=0;msg="invalid id or storage error";}break;
                case MON_STATUS: {
                    struct config c;unsigned q;
                    pthread_mutex_lock(&shared.mu);c=shared.cfg;q=shared.count;pthread_mutex_unlock(&shared.mu);
                    snprintf(json,sizeof(json),"{\"ok\":true,\"period_ms\":%u,\"light_raw\":%u,\"motion_raw\":%u,\"pending\":%d,\"queue\":%u,\"storage_errors\":%u,\"tx_errors\":%u,\"bad_crc\":%u}",c.period_ms,c.light_raw,c.motion_raw,event_count(dir),q,storage_errors,tx_errors,parser.bad_crc);
                    if(send_text(fd,MON_REPLY,f.seq,json))tx_errors++;continue; }
                default:ok=0;msg="unknown command";break;
                }
                if(reply(fd,&f,ok,msg))tx_errors++;
            }
        }
        /* Only this thread writes the journal. Sampling does not wait for UART/disk. */
        if(pop_event(&s)) {
            char id[32];snprintf(id,sizeof(id),"%016" PRIx64 "-%08x",boot,++event_seq);
            snprintf(json,sizeof(json),"{\"id\":\"%s\",\"ms\":%" PRIu64 ",\"als\":%d,\"motion\":%d}",id,s.ms,s.als,s.motion);
            if(event_save(dir,id,json)){storage_errors++;fprintf(stderr,"event journal failed/full: %s\n",id);}
        }
        if(connected&&now_ms()-last_rx>6000)connected=0;
        pthread_mutex_lock(&shared.mu);s=shared.latest;gen=shared.generation;drops=shared.overruns;errs=shared.errors;pthread_mutex_unlock(&shared.mu);
        if(connected&&gen!=last_gen) {
            last_gen=gen;
            snprintf(json,sizeof(json),"{\"ms\":%" PRIu64 ",\"als\":%d,\"ax\":%d,\"ay\":%d,\"az\":%d,\"gx\":%d,\"gy\":%d,\"gz\":%d,\"motion\":%d,\"valid\":%d,\"alarm\":%d,\"dropped\":%u,\"sensor_errors\":%u}",s.ms,s.als,s.ax,s.ay,s.az,s.gx,s.gy,s.gz,s.motion,s.valid,s.alarm,drops,errs);
            if(send_text(fd,MON_SAMPLE,++wire_seq,json))tx_errors++;
        }
        if(connected&&now_ms()-last_event>=500) {
            int er=event_next(dir,cursor,json,sizeof(json));last_event=now_ms();
            if(!er){cursor=0;er=event_next(dir,cursor,json,sizeof(json));}
            if(er>0){cursor++;if(send_text(fd,MON_EVENT,++wire_seq,json))tx_errors++;}
            else if(er<0)storage_errors++;
        }
    }
finish:
    stopping=1;if(started)pthread_join(thread,NULL);
    if(started) { struct sample pending;
        while(pop_event(&pending)) {
            char id[32];snprintf(id,sizeof(id),"%016" PRIx64 "-%08x",boot,++event_seq);
            snprintf(json,sizeof(json),"{\"id\":\"%s\",\"ms\":%" PRIu64 ",\"als\":%d,\"motion\":%d}",id,pending.ms,pending.als,pending.motion);
            if(event_save(dir,id,json)){perror("shutdown event persistence");rc=1;}
        }
    }
    sensors_close(&shared.hw);tcsetattr(fd,TCSANOW,&saved);close(fd);
cleanup:
    if(lockfd>=0)close(lockfd);return rc;
}
