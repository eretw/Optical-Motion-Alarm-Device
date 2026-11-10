#include "protocol.h"
#include <string.h>
static uint16_t le16(const uint8_t *p) { return (uint16_t)(p[0] | ((uint16_t)p[1]<<8)); }
static void put16(uint8_t *p, uint16_t x) { p[0]=(uint8_t)x; p[1]=(uint8_t)(x>>8); }
uint16_t mon_crc(const uint8_t *p, size_t n)
{
    uint16_t crc=0xffff; size_t i; unsigned bit;
    for(i=0;i<n;i++) { crc^=(uint16_t)p[i]<<8;
        for(bit=0;bit<8;bit++) crc=(uint16_t)((crc&0x8000)?(crc<<1)^0x1021:crc<<1);
    } return crc;
}
size_t mon_encode(uint8_t *out, uint8_t type, uint16_t seq, const void *payload, size_t len)
{
    if(len>MON_PAYLOAD_MAX) return 0;
    out[0]=0xa5; out[1]=0x5a; out[2]=1; out[3]=type;
    put16(out+4,seq); put16(out+6,(uint16_t)len);
    if(len) memcpy(out+8,payload,len);
    put16(out+8+len,mon_crc(out+2,6+len)); return len+10;
}
static void drop(struct mon_parser *p) { memmove(p->data,p->data+1,--p->used); }
int mon_feed(struct mon_parser *p, uint8_t byte, struct mon_frame *out)
{
    size_t total; uint16_t len;
    if(p->used==sizeof(p->data)) drop(p);
    p->data[p->used++]=byte;
    while(p->used) {
        if(p->data[0]!=0xa5) { drop(p); continue; }
        if(p->used<2) return 0;
        if(p->data[1]!=0x5a) { drop(p); continue; }
        if(p->used<8) return 0;
        len=le16(p->data+6);
        if(p->data[2]!=1 || len>MON_PAYLOAD_MAX) { p->bad_header++; drop(p); continue; }
        total=(size_t)len+10;
        if(p->used<total) return 0;
        if(le16(p->data+8+len)!=mon_crc(p->data+2,6+len)) { p->bad_crc++; drop(p); continue; }
        out->type=p->data[3]; out->seq=le16(p->data+4); out->len=len;
        memcpy(out->payload,p->data+8,len); out->payload[len]=0;
        memmove(p->data,p->data+total,p->used-total); p->used-=total; return 1;
    } return 0;
}
void mon_expire(struct mon_parser *p) { p->used=0; }
