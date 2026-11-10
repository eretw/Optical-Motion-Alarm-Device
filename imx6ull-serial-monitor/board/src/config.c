#include "monitor.h"
#include <stdlib.h>
#include <errno.h>
/* Reject signs, whitespace, overflow and trailing data. Never partially apply. */
int config_parse(const char *s,struct config *c) // 参数校验
{
    unsigned long v[3];
	int i;
	char *end;
    for(i=0;i<3;i++) {
        if(*s<'0'||*s>'9')return -1;
        errno=0;
		v[i]=strtoul(s,&end,10);
        if(errno || v[i]>65535 || (i<2?*end!=',':*end!='\0'))return -1;
        s=end+(i<2);
    }
    if(v[0]<200||v[0]>10000||v[2]<1)return -1;
    c->period_ms=(unsigned)v[0];
	c->light_raw=(unsigned)v[1];
	c->motion_raw=(unsigned)v[2];
	return 0;
}
