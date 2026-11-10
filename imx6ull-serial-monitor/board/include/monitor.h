#ifndef MONITOR_H
#define MONITOR_H
#include <stdint.h>
#include <stddef.h>
struct termios;
struct config { unsigned period_ms, light_raw, motion_raw; };
struct sample { uint64_t ms; int als, ax, ay, az, gx, gy, gz, motion, valid, alarm; };
struct sensors { int ap, imu, key, mock; unsigned tick; int prev[3], have_prev; const char *beep, *led; };
uint64_t now_ms(void);
int serial_open(const char *path, struct termios *saved);
int write_deadline(int fd, const void *buf, size_t n, unsigned timeout_ms);
int sensors_open(struct sensors *s, int mock, const char *key);
void sensors_read(struct sensors *s, struct sample *out);
void sensors_alarm(struct sensors *s, int on);
int sensors_key(struct sensors *s);
void sensors_close(struct sensors *s);
int config_parse(const char *str, struct config *cfg);
int config_load(const char *dir, struct config *cfg);
int config_save(const char *dir, const struct config *cfg);
int event_save(const char *dir, const char *id, const char *json);
int event_ack(const char *dir, const char *id);
int event_next(const char *dir, unsigned cursor, char *json, size_t cap);
int event_count(const char *dir);
int valid_event_id(const char *id);
#endif
