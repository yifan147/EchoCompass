# EchoCompass 回声罗盘

A sound-direction radar for deaf and hard-of-hearing FPS players: it listens to the game's binaural (headphone) audio output and translates gunshots and footsteps into a visual compass — on your PC, on an ESP32 round LCD, or on your phone.

给听障 FPS 玩家的声音方向雷达。监听游戏发给耳机的双耳音频,把枪声和脚步的方向翻译成画面——电脑窗口、ESP32 圆屏、手机浏览器,三块屏任选。

## 它做什么

- **方向雷达**:枪声显示为红色尖刺星形,脚步显示为蓝色圆点,左右方向(±90°)实时指示
- **突发威胁警报**:长时间安静后突然出现枪声,整屏红光爆闪三下,余光可及
- **手机即雷达**:无需任何硬件,手机浏览器打开即用,与圆屏画面同步

听得见的人用耳朵,听不见的人用眼睛。信息是同一份,谁也没多拿。

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

游戏内设置(以三角洲行动为例):声音输出模式选 **耳机**,HRTF 开 **基于对象的双耳声**,输出设备为系统默认播放设备。

手机雷达:手机与电脑同一局域网,浏览器打开 `http://<电脑IP>:8090`,点全屏。

## 硬件圆屏(可选)

- 板子:ESP32-S3 + 1.28 寸 GC9A01 圆屏(240×240,如 Waveshare ESP32-S3-Touch-LCD-1.28)
- 固件:`echo_compass_fw/echo_compass_fw.ino`,依赖 TFT_eSPI 库
- 引脚在 TFT_eSPI 的 `User_Setup.h` 中配置:`MOSI=11 SCLK=10 CS=9 DC=8 RST=12 BL=40`,`GC9A01_DRIVER` + `USE_HSPI_PORT`
- 烧录后插 USB,程序启动时自动识别串口(CH343);**先插圆屏,再启动 main.py**

## 工作原理

现代 FPS(三角洲行动、无畏契约等)并不输出真正的多声道环绕,方位信息全部编码在发给耳机的两个声道里。人耳分左右靠的是高频的双耳响度差(头影效应),低频绕过头部、两耳几乎无差。程序在声音起音的瞬间截取直达声小窗,滤掉低频后计算两耳响度差,换算成角度。纯信号处理,零模型、零训练数据、零联网。

## 已知边界(如实说)

- **前后方向分不出来**。两声道双耳信号里前后线索只剩微弱的频谱染色,这是物理边界,规则法无解,业内用模型也只做到约七成
- **嘈杂野外的远处轻脚步检测不到**。-38dB 的脚步泡在 -35dB 的风声鸟叫里,能量法原理上分不开
- 多个声源同时发声只显示其中之一

## 它和外挂是两个物种

本工具**不碰游戏进程、不读内存、不看画面、不碰输入**,唯一的信息来源是操作系统的音频输出——也就是你耳机里正在播放的那份声音。它做的事情只有一件:把听力玩家本来就免费拥有的信息,还给听不见的玩家。

## Roadmap

- 前后方向:HRTF 高频频谱特征 + 轻量模型(业内已验证约 70% 可达)
- 灵敏模式调优:安静场景轻脚步检测(代码中已有开关 `SIMPLE_MODE=False`)
- 脚步/枪声分类升级:1D-CNN 替代响度规则

## License

MIT
