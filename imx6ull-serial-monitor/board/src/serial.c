#define _DEFAULT_SOURCE
#include "monitor.h"
#include <termios.h>
#include <unistd.h>
#include <fcntl.h>
#include <errno.h>
#include <poll.h>
#include <time.h>
#include <sys/ioctl.h>
uint64_t now_ms(void) { struct timespec t; clock_gettime(CLOCK_MONOTONIC,&t); return (uint64_t)t.tv_sec*1000+t.tv_nsec/1000000; }
int serial_open(const char *path, struct termios *saved)
{
    int fd=open(path,O_RDWR|O_NOCTTY|O_NONBLOCK); struct termios t;
    if(fd<0) return -1;
    if(tcgetattr(fd,saved)) { close(fd); return -1; }
    t=*saved; cfmakeraw(&t); cfsetispeed(&t,B115200); cfsetospeed(&t,B115200);
    t.c_cflag|=CLOCAL|CREAD; t.c_cflag&=~(CRTSCTS|CSTOPB|PARENB|CSIZE); t.c_cflag|=CS8;
    t.c_cc[VMIN]=0; t.c_cc[VTIME]=0;
    if(tcsetattr(fd,TCSANOW,&t)) { close(fd); return -1; }
    tcflush(fd,TCIOFLUSH); return fd;
}
int write_deadline(int fd, const void *buf, size_t n, unsigned timeout_ms)
{
    const unsigned char *p=buf; uint64_t end=now_ms()+timeout_ms;
    while(n) {
        ssize_t r=write(fd,p,n);
        if(r>0) { p+=r; n-=(size_t)r; continue; }
        if(r<0 && errno!=EINTR && errno!=EAGAIN && errno!=EWOULDBLOCK) return -1;
        if(now_ms()>=end) { errno=ETIMEDOUT; return -1; }
        { struct pollfd pf={fd,POLLOUT,0}; int ret=poll(&pf,1,20);
          if(ret<0 && errno!=EINTR) return -1;
          if(ret>0 && (pf.revents&(POLLERR|POLLHUP|POLLNVAL))) return -1; }
    } return 0;
}
