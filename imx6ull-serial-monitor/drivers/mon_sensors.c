// SPDX-License-Identifier: GPL-2.0-only
/* Teaching driver for ALPHA / Linux 4.1.15. New implementation, no vendor source copied.
 * ABI: /dev/mon_ap3216c reads 6 raw bytes from 0x0a;
 *      /dev/mon_icm20608 reads 14 raw bytes from 0x3b.
 * Use existing gpio-leds and gpio-keys for outputs and buttons.
 */
#include <linux/module.h>
#include <linux/i2c.h>
#include <linux/spi/spi.h>
#include <linux/miscdevice.h>
#include <linux/fs.h>
#include <linux/uaccess.h>
#include <linux/mutex.h>
#include <linux/delay.h>
#include <linux/of.h>
// 保存一个传感器的运行状态
struct sensor {
    struct miscdevice misc;//用于向 Linux 注册一个杂项字符设备
    struct mutex lock; // 	互斥锁，协调读操作与设备解绑
    struct i2c_client *i2c; // 	指向 I2C 设备，AP3216C 使用
    struct spi_device *spi; // 	指向 SPI 设备，ICM20608 使用
    bool ready; // 表示设备是否已初始化、可以读取
    unsigned int length; //	一次读取返回的字节数
};
/* Static lifetime plus fops.owner prevents open-file use-after-free on unbind.
 * This board-specific module deliberately supports one sensor of each type.
 */
static struct sensor light, imu; // 创建两个实例

// 封装 AP3216C 的寄存器访问
static int ap_read(struct i2c_client *c,// 哪个 I2C 设备
						u8 reg, // 从哪个寄存器开始读
						u8 *buf, // 数据放到哪里
						unsigned int n) // 读取多少字节
{
    struct i2c_msg messages[2] = {
        {.addr=c->addr,
		.len=1,
		.buf=&reg},
        {.addr=c->addr,
		.flags=I2C_M_RD,
		.len=n,
		.buf=buf}
    };
    int ret=i2c_transfer(c->adapter,messages,2);
    return ret==2?0:(ret<0?ret:-EIO);
}
static int ap_write(struct i2c_client *c,
						u8 reg,
						u8 value)
{
    u8 b[2]={reg,value};
	int ret=i2c_master_send(c,b,sizeof(b));
    return ret==sizeof(b)?0:(ret<0?ret:-EIO);
}
// 封装 ICM20608 的 SPI 访问
static int imu_read(struct spi_device *s,
						u8 reg,
						u8 *buf,
						unsigned int n)
{ u8 cmd=reg|0x80;// 最高位区分读写
return spi_write_then_read(s,&cmd,1,buf,n); 
}

static int imu_write(struct spi_device *s,
						u8 reg,
						u8 value)
{ 
u8 b[2]={reg&0x7f,value};
return spi_write(s,b,sizeof(b)); 
}

static ssize_t sensor_read(struct file *file, // 本次打开的文件对象
							char __user *user, // 应用提供的用户空间缓冲区
							size_t size, //	应用希望读取的最大字节数
							loff_t *offset)
{
    struct miscdevice *misc=file->private_data;// 找出当前正在读取哪个传感器
    struct sensor *s=container_of(misc,struct sensor,misc);
    u8 data[14];
	int ret;
    (void)offset;
    if(size<s->length)return -EINVAL; // 检查缓冲区的大小
	// 加锁并访问设备
    if(mutex_lock_interruptible(&s->lock)) return -ERESTARTSYS;
    if(!s->ready)ret=-ENODEV;
    else if(s->i2c)ret=ap_read(s->i2c,0x0a,data,s->length);
    else ret=imu_read(s->spi,0x3b,data,s->length);
    mutex_unlock(&s->lock);
    if(ret) return ret;
    if(copy_to_user(user,data,s->length))return -EFAULT;
    return s->length; /* POSIX byte count; never report EOF after copying a sample. */
}
static const struct file_operations sensor_ops = {
    .owner=THIS_MODULE, // 文件操作属于当前模块，使正常模块卸载遵守引用计数。
	.read=sensor_read,
	.llseek=no_llseek  // 设备不支持普通文件式的位置跳转
};
// 初始化 AP3216C 并创建设备节点
static int ap_probe(struct i2c_client *c,
					const struct i2c_device_id *id)
{
    int ret;
	u8 mode;
	(void)id;
    if(!i2c_check_functionality(c->adapter,I2C_FUNC_I2C)) return -EOPNOTSUPP;// 确认 I2C 控制器支持需要的传输方式
    mutex_lock(&light.lock);
    if(light.i2c)// 然后检查是否已经有一个 AP3216C
	{
		ret=-EBUSY;
		goto out;
	}
    ret=ap_write(c,0x00,0x04);
	if(ret)goto out;
    msleep(50);
	ret=ap_write(c,0x00,0x03);
	if(ret)goto out;
    msleep(120);
	ret=ap_read(c,0x00,&mode,1);
	if(ret)goto out;
    if((mode&7)!=3) // 检查低3位
	{
		ret=-ENODEV;
		goto out;
	}
    light.i2c=c;
	light.length=6;
	light.ready=true;
	light.misc.parent=&c->dev;
    ret=misc_register(&light.misc);// 保存状态并注册字符设备
    if(ret)
	{
		light.ready=false;
		light.i2c=NULL;
	}
    else dev_info(&c->dev,"AP3216C ready: /dev/mon_ap3216c\n");
out:// 把错误处理集中到同一个出口
mutex_unlock(&light.lock);
return ret;
}
static int ap_remove(struct i2c_client *c)
{
    (void)c;misc_deregister(&light.misc);mutex_lock(&light.lock);
    light.ready=false;light.i2c=NULL;mutex_unlock(&light.lock);return 0;
}
// 设备树匹配表
static const struct of_device_id ap_of[]={{.compatible="study,mon-ap3216c"},{}};
static const struct i2c_device_id ap_ids[]={{"mon-ap3216c",0},{}};
MODULE_DEVICE_TABLE(of,ap_of);MODULE_DEVICE_TABLE(i2c,ap_ids);
// ap_of[]数组仅仅定义出来还不够，必须接到驱动结构体上
static struct i2c_driver ap_driver={
    .driver={
		.name="mon-ap3216c",
		.of_match_table=ap_of
	},
    .probe=ap_probe,
	.remove=ap_remove,
	.id_table=ap_ids
};

static int imu_probe(struct spi_device *s)
{
    int ret;
	u8 who;
	unsigned int i;
    static const u8 setup[][2]={
        {0x6b,0x01},{0x6c,0x00},{0x19,0x09}, /* 100Hz with DLPF; app reads at <=5Hz */
        {0x1a,0x04},{0x1b,0x00},{0x1c,0x00}, /* +-250 dps, +-2g */
        {0x1d,0x04},{0x1e,0x00},{0x23,0x00},{0x38,0x00},{0x6a,0x10}
    };
    mutex_lock(&imu.lock);
	// 设置总线参数
    if(imu.spi){ret=-EBUSY;goto out;}
    s->mode=SPI_MODE_0;
	s->bits_per_word=8;
    if(s->max_speed_hz>8000000) s->max_speed_hz=8000000;
    ret=spi_setup(s);
	// 复位芯片、读取身份寄存器
	if(ret)goto out;
    ret=imu_write(s,0x6b,0x80);
	if(ret)goto out;
	msleep(100);
    ret=imu_read(s,0x75,&who,1);
	
	if(ret)goto out;
	// 部分通信错误或器件不匹配问题
    if(who!=0xaf && who!=0xae)
	{
		dev_err(&s->dev,"unexpected WHO_AM_I=%02x\n",who);
		ret=-ENODEV;
		goto out;
	}
    for(i=0;i<ARRAY_SIZE(setup);i++)
	{
		ret=imu_write(s,setup[i][0],setup[i][1]);
		if(ret)goto out;
	}
    msleep(100);
	imu.spi=s;
	imu.length=14;
	imu.ready=true;
	imu.misc.parent=&s->dev;
    ret=misc_register(&imu.misc);
    if(ret){imu.ready=false;imu.spi=NULL;}
    else dev_info(&s->dev,"ICM20608 ready: /dev/mon_icm20608, +/-2g\n");
out:mutex_unlock(&imu.lock);return ret;
}
static int imu_remove(struct spi_device *s)
{
    (void)s;misc_deregister(&imu.misc);mutex_lock(&imu.lock);
    imu.ready=false;imu.spi=NULL;mutex_unlock(&imu.lock);return 0;
}

static const struct of_device_id imu_of[]={{.compatible="study,mon-icm20608"},{}};
static const struct spi_device_id imu_ids[]={{"mon-icm20608",0},{}};
MODULE_DEVICE_TABLE(of,imu_of);MODULE_DEVICE_TABLE(spi,imu_ids);
static struct spi_driver imu_driver={
    .driver={.name="mon-icm20608",.of_match_table=imu_of},
    .probe=imu_probe,.remove=imu_remove,.id_table=imu_ids
};
static int __init monitor_init(void)
{
    int ret;
	mutex_init(&light.lock);
	mutex_init(&imu.lock);
    light.misc.minor=MISC_DYNAMIC_MINOR;
	light.misc.name="mon_ap3216c";
	light.misc.fops=&sensor_ops;
    imu.misc.minor=MISC_DYNAMIC_MINOR;
	imu.misc.name="mon_icm20608";
	imu.misc.fops=&sensor_ops;
    ret=i2c_add_driver(&ap_driver);
	if(ret)return ret;
    ret=spi_register_driver(&imu_driver);
	if(ret)i2c_del_driver(&ap_driver);
	return ret;
}
static void __exit monitor_exit(void) { spi_unregister_driver(&imu_driver);i2c_del_driver(&ap_driver); }
module_init(monitor_init);
module_exit(monitor_exit);
MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("ALPHA learning project AP3216C and ICM20608 character drivers");
