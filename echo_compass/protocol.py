"""
Echo Compass - 数据结构与串口协议
电脑端和硬件端共用的数据格式
"""

import struct
from dataclasses import dataclass


SOUND_TYPE_SILENCE = 0
SOUND_TYPE_FOOTSTEP = 1
SOUND_TYPE_GUNSHOT = 2
SOUND_TYPE_OTHER = 3

SOUND_TYPE_NAMES = {
    0: '静音',
    1: '脚步',
    2: '枪声',
    3: '其他',
}

FRAME_HEADER = 0xAA
FRAME_SIZE = 8


@dataclass
class CompassData:
    """
    罗盘数据（统一数据结构）
    
    电脑端算法输出这个结构，UI 和串口发送都用它
    ESP32 硬件端也接收同样的数据并显示
    """
    has_sound: bool = False
    angle: float = 0.0       # 度，0=正前方，顺时针，范围 0~360
    distance: float = 1.0    # 0~1，0=最近，1=最远
    sound_type: int = SOUND_TYPE_SILENCE  # 0=静音 1=脚步 2=枪声 3=其他
    energy: float = 0.0      # 总能量 0~1
    confidence: float = 0.0  # 方向置信度 0~1

    def normalize_angle(self):
        """角度归一化到 0~360"""
        while self.angle < 0:
            self.angle += 360
        while self.angle >= 360:
            self.angle -= 360


def serialize(data: CompassData) -> bytes:
    """
    序列化为串口二进制帧
    
    帧格式（8字节）:
    ┌─────────┬─────────┬──────────┬──────────┬──────────┬─────────┬──────────┬─────────┐
    │ 帧头    │ 类型    │ 角度高   │ 角度低   │ 距离    │ 能量    │ 保留    │ 校验   │
    │ 0xAA   │ 1字节  │ 1字节   │ 1字节   │ 1字节  │ 1字节  │ 1字节  │ 1字节  │
    └─────────┴─────────┴──────────┴──────────┴──────────┴─────────┴──────────┴─────────┘
    
    角度: 0~3600 (0.1度精度)，高8位+低8位
    距离: 0~100
    能量: 0~255
    校验: 前面7字节的异或
    """
    angle_int = int(max(0, min(3600, data.angle * 10)))
    angle_high = (angle_int >> 8) & 0xFF
    angle_low = angle_int & 0xFF
    
    dist_int = int(max(0, min(100, data.distance * 100)))
    energy_int = int(max(0, min(255, data.energy * 255)))
    type_int = data.sound_type if data.has_sound else 0
    
    frame = bytearray(FRAME_SIZE)
    frame[0] = FRAME_HEADER
    frame[1] = type_int & 0xFF
    frame[2] = angle_high
    frame[3] = angle_low
    frame[4] = dist_int & 0xFF
    frame[5] = energy_int & 0xFF
    frame[6] = 0  # 保留
    
    # 校验：前7字节异或
    checksum = 0
    for i in range(7):
        checksum ^= frame[i]
    frame[7] = checksum & 0xFF
    
    return bytes(frame)


def deserialize(frame: bytes) -> CompassData:
    """从串口帧反序列化为数据"""
    if len(frame) < FRAME_SIZE:
        return CompassData()
    if frame[0] != FRAME_HEADER:
        return CompassData()
    
    # 校验
    checksum = 0
    for i in range(7):
        checksum ^= frame[i]
    if (checksum & 0xFF) != frame[7]:
        return CompassData()
    
    type_int = frame[1]
    angle_high = frame[2]
    angle_low = frame[3]
    dist_int = frame[4]
    energy_int = frame[5]
    
    angle_int = (angle_high << 8) | angle_low
    angle = angle_int / 10.0
    distance = dist_int / 100.0
    energy = energy_int / 255.0
    
    has_sound = type_int > 0
    
    return CompassData(
        has_sound=has_sound,
        angle=angle,
        distance=distance,
        sound_type=type_int,
        energy=energy,
        confidence=0.0,
    )
