#ifndef MON_PROTOCOL_H
#define MON_PROTOCOL_H
#include <stddef.h>
#include <stdint.h>
#define MON_PAYLOAD_MAX 256
#define MON_FRAME_MAX (MON_PAYLOAD_MAX + 10)
enum { MON_HELLO=1, MON_CONFIG=2, MON_SILENCE=3, MON_STOP=4,
       MON_EVENT_ACK=5, MON_STATUS=6, MON_REPLY=0x80,
       MON_SAMPLE=0x81, MON_EVENT=0x82 };
struct mon_frame { uint8_t type; uint16_t seq, len; uint8_t payload[MON_PAYLOAD_MAX+1]; };// 帧结构和消息类型
struct mon_parser { uint8_t data[MON_FRAME_MAX]; size_t used; uint32_t bad_crc, bad_header; };
uint16_t mon_crc(const uint8_t *data, size_t size);
size_t mon_encode(uint8_t *out, uint8_t type, uint16_t seq, const void *payload, size_t len);
/* Call once for each byte. A complete, validated frame returns 1. */
int mon_feed(struct mon_parser *p, uint8_t byte, struct mon_frame *out);
void mon_expire(struct mon_parser *p);
#endif
