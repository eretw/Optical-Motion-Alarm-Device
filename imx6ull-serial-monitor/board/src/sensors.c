#include "monitor.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <unistd.h>
#include <fcntl.h>
#include <linux/input.h>
static int s16(const unsigned char *b) { unsigned v=((unsigned)b[0]<<8)|b[1]; return v&0x8000?(int)v-65536:(int)v; }
static void output(const char *path, const char *value)
{ int fd=open(path,O_WRONLY); if(fd>=0) { (void)write(fd,value,strlen(value)); close(fd); } }
int sensors_open(struct sensors *s, int mock, const char *key)
{
    memset(s,0,sizeof(*s)); s->ap=s->imu=s->key=-1; s->mock=mock;
    s->beep="/sys/class/leds/beep/brightness"; s->led="/sys/class/leds/sys-led/brightness";
    if(mock) return 0;
    s->ap=open("/dev/mon_ap3216c",O_RDONLY); s->imu=open("/dev/mon_icm20608",O_RDONLY);
    if(s->ap<0 || s->imu<0) { sensors_close(s); return -1; }
    if(key) { s->key=open(key,O_RDONLY|O_NONBLOCK); if(s->key<0) { sensors_close(s); return -1; } }
    /* Existing gpio-leds and gpio-keys drivers own these GPIOs. Do not request twice. */
    output("/sys/class/leds/sys-led/trigger","none");
    output("/sys/class/leds/beep/trigger","none"); sensors_alarm(s,0); return 0;
}
void sensors_read(struct sensors *s, struct sample *o)
{
    unsigned char a[6],b[14]; int i,xyz[3]; memset(o,0,sizeof(*o)); o->ms=now_ms();
    if(s->mock) {
        s->tick++; o->als=(s->tick%60>=40 && s->tick%60<45)?4000:120;
        o->ax=s->tick%30==0?8000:0; o->ay=0; o->az=16384; o->valid=1;
    } else {
        if(read(s->ap,a,sizeof(a))!=sizeof(a) || read(s->imu,b,sizeof(b))!=sizeof(b)) return;
        o->als=a[2]|((int)a[3]<<8);
        o->ax=s16(b);o->ay=s16(b+2);o->az=s16(b+4);
        o->gx=s16(b+8);o->gy=s16(b+10);o->gz=s16(b+12);o->valid=1;
    }
    xyz[0]=o->ax;xyz[1]=o->ay;xyz[2]=o->az;
    for(i=0;i<3;i++) { int d=abs(xyz[i]-s->prev[i]); if(s->have_prev && d>o->motion) o->motion=d; s->prev[i]=xyz[i]; }
    s->have_prev=1;
}
void sensors_alarm(struct sensors *s,int on) // 控制蜂鸣器和LED
{ 
	if(!s->mock) { 
		output(s->beep,on?"1":"0");
		output(s->led,on?"1":"0"); 
		} 
}
int sensors_key(struct sensors *s)
{
    struct input_event e; 
	int pressed=0;
    while(s->key>=0 && read(s->key,&e,sizeof(e))==sizeof(e))
        if(e.type==EV_KEY && (e.code==KEY_0 || e.code==KEY_VOLUMEDOWN) && e.value==1) pressed=1;
    return pressed;
}
void sensors_close(struct sensors *s)
{
    sensors_alarm(s,0);
    if(s->ap>=0)close(s->ap);
	if(s->imu>=0)close(s->imu); 
	if(s->key>=0)close(s->key);
    s->ap=s->imu=s->key=-1;
}
