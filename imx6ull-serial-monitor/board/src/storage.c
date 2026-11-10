#define _POSIX_C_SOURCE 200809L
#include "monitor.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <ctype.h>
#include <errno.h>
#include <unistd.h>
#include <fcntl.h>
#include <dirent.h>
#include <sys/stat.h>
static int dir_sync(const char *dir) { int fd=open(dir,O_RDONLY|O_DIRECTORY),r; if(fd<0)return -1;r=fsync(fd);close(fd);return r; }
static int atomic_save(const char *dir,const char *name,const char *data)
{
    char dest[512],tmp[512]; int fd,rc=0; size_t left=strlen(data); const char *p=data;
    if(snprintf(dest,sizeof(dest),"%s/%s",dir,name)>=(int)sizeof(dest) || snprintf(tmp,sizeof(tmp),"%s/.pending",dir)>=(int)sizeof(tmp))return -1;
    fd=open(tmp,O_WRONLY|O_CREAT|O_TRUNC,0600);if(fd<0)return -1;
    while(left) { ssize_t w=write(fd,p,left);if(w<0&&errno==EINTR)continue;if(w<=0){rc=-1;break;}p+=w;left-=(size_t)w; }
    if(!rc && fsync(fd))rc=-1;
    if(close(fd))rc=-1;
    if(!rc && rename(tmp,dest))rc=-1;
    if(!rc && dir_sync(dir))rc=-1;
    return rc;
}
int config_save(const char *dir,const struct config *c) { char b[80];snprintf(b,sizeof(b),"%u,%u,%u",c->period_ms,c->light_raw,c->motion_raw);return atomic_save(dir,"config",b); }
int config_load(const char *dir,struct config *c)
{
    char path[512],b[81]; FILE *f; size_t n;
    snprintf(path,sizeof(path),"%s/config",dir);f=fopen(path,"rb");if(!f)return errno==ENOENT?1:-1;
    n=fread(b,1,sizeof(b)-1,f);b[n]=0;
    if(ferror(f)||!feof(f)){fclose(f);return -1;} fclose(f);return config_parse(b,c);
}
int valid_event_id(const char *id)
{
    size_t i;if(strlen(id)!=25||id[16]!='-')return 0;
    for(i=0;i<25;i++)if(i!=16&&!((id[i]>='0'&&id[i]<='9')||(id[i]>='a'&&id[i]<='f')))return 0;
    return 1;
}
static int is_event(const char *n) { return !strncmp(n,"event-",6)&&valid_event_id(n+6); }
int event_count(const char *dir)
{ DIR *d=opendir(dir);struct dirent *e;int n=0;if(!d)return -1;while((e=readdir(d)))if(is_event(e->d_name))n++;closedir(d);return n; }
int event_save(const char *dir,const char *id,const char *json)
{
    char name[40];int n=event_count(dir);if(!valid_event_id(id)||n<0)return -1;if(n>=128){errno=ENOSPC;return -1;}
    snprintf(name,sizeof(name),"event-%s",id);return atomic_save(dir,name,json);
}
int event_ack(const char *dir,const char *id)
{
    char path[512];if(!valid_event_id(id))return -1;
    snprintf(path,sizeof(path),"%s/event-%s",dir,id);
    if(unlink(path)&&errno!=ENOENT)return -1;return dir_sync(dir);
}
int event_next(const char *dir,unsigned cursor,char *json,size_t cap)
{
    DIR *d=opendir(dir);struct dirent *e;unsigned i=0;char path[512];FILE *f;size_t n;
    if(!d)return -1;
    while((e=readdir(d)))if(is_event(e->d_name)&&i++==cursor) {
        snprintf(path,sizeof(path),"%s/%s",dir,e->d_name);closedir(d);f=fopen(path,"rb");if(!f)return -1;
        n=fread(json,1,cap-1,f);json[n]=0;
        if(ferror(f)||!feof(f)){fclose(f);return -1;}fclose(f);return 1;
    }
    closedir(d);return 0;
}
