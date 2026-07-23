"""
Echo Compass - 8声道信号发生器
给定方向、距离、声音类型，生成 7.1 声道音频
用于测试方向计算和分类器
"""

import numpy as np

SAMPLE_RATE = 48000

# 7.1 声道角度定义（标准 Windows 7.1 声道顺序）
# 角度：0=正前方，顺时针为正
CHANNEL_ANGLES = {
    0: -30,   # FL 前左
    1: 30,    # FR 前右
    2: 0,     # FC 中置
    3: None,  # LFE 低音（全向）
    4: -150,  # RL 后左
    5: 150,   # RR 后右
    6: -90,   # SL 侧左
    7: 90,    # SR 侧右
}

CHANNEL_NAMES = ["FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"]


def normalize_angle(angle):
    """角度归一化到 [-180, 180]"""
    while angle > 180:
        angle -= 360
    while angle <= -180:
        angle += 360
    return angle


def calc_channel_gains(source_angle, spread=40.0):
    """
    计算 8 个声道的增益（0~1
    
    参数:
        source_angle: 声源角度（度），0=正前方，顺时针为正
        spread: 扩散角（度），越小方向性越强
    
    返回:
        gains: shape (8,) 数组，每个声道 0~1 的增益
    """
    source_angle = normalize_angle(source_angle)
    gains = np.zeros(8)

    for ch in range(8):
        if ch == 3:  # LFE 全向
            gains[ch] = 1.0
            continue

        ch_angle = CHANNEL_ANGLES[ch]
        # 计算角度差
        diff = abs(normalize_angle(source_angle - ch_angle))
        # 余弦扩散模型：角度差为0时增益1，diff >= spread时增益接近0
        if diff >= spread:
            gains[ch] = 0.0
        else:
            gains[ch] = np.cos(np.radians(diff * 90 / spread))
            gains[ch] = max(0.0, min(1.0, gains[ch]))

    return gains


def generate_footstep(duration=0.15, sample_rate=SAMPLE_RATE):
    """
    生成单步声波形
    
    特征：低频为主（100~500Hz)，缓慢起始，自然衰减
    """
    n = int(duration * sample_rate)
    t = np.linspace(0, duration, n, endpoint=False)

    # 多频率叠加，模拟脚步声
    freqs = [120, 180, 250, 350]
    signal = np.zeros(n)
    for f in freqs:
        signal += np.sin(2 * np.pi * f * t) / len(freqs)

    # 包络：缓慢攻击 + 指数衰减
    attack = int(0.02 * sample_rate)  # 20ms 攻击
    envelope = np.ones(n)
    envelope[:attack] = np.linspace(0, 1, attack)
    # 衰减
    decay_len = n - attack
    envelope[attack:] = np.exp(-np.linspace(0, 5, decay_len))

    signal *= envelope

    # 归一化
    max_val = np.max(np.abs(signal))
    if max_val > 0:
        signal /= max_val

    return signal


def generate_gunshot(duration=0.15, sample_rate=SAMPLE_RATE):
    """
    生成枪声波形
    
    特征：全频段噪声 + 极快起始 + 快速衰减
    """
    n = int(duration * sample_rate)

    # 白噪声为基础
    noise = np.random.randn(n)

    # 加上一些低频冲击成分
    t = np.linspace(0, duration, n, endpoint=False)
    low_freq = np.sin(2 * np.pi * 150 * t) * np.exp(-t * 30)
    mid_freq = np.sin(2 * np.pi * 800 * t) * np.exp(-t * 50)

    signal = noise * 0.6 + low_freq * 0.25 + mid_freq * 0.15

    # 包络：极快攻击（几乎瞬时）+ 快速衰减
    attack = int(0.002 * sample_rate)  # 2ms 攻击
    envelope = np.ones(n)
    envelope[:attack] = np.linspace(0, 1, attack)
    decay_len = n - attack
    envelope[attack:] = np.exp(-np.linspace(0, 8, decay_len))

    signal *= envelope

    # 归一化
    max_val = np.max(np.abs(signal))
    if max_val > 0:
        signal /= max_val

    return signal


def generate_71_signal(sound_type, angle, distance=0.5, duration=None, sample_rate=SAMPLE_RATE):
    """
    生成 7.1 声道音频信号

    参数:
        sound_type: 'footstep' 或 'gunshot'
        angle: 方向角度（度），0=正前方，顺时针为正
        distance: 距离 0~1，0=最近，1=最远
        duration: 持续时间（秒），None则用默认值
        sample_rate: 采样率

    返回:
        signal_71: shape (n_samples, 8) 数组
    """
    # 生成单声道源信号
    if sound_type == 'footstep':
        if duration is None:
            duration = 0.15
        source = generate_footstep(duration, sample_rate)
    elif sound_type == 'gunshot':
        if duration is None:
            duration = 0.2
        source = generate_gunshot(duration, sample_rate)
    else:
        raise ValueError(f"未知声音类型: {sound_type}")

    # 计算声道增益
    gains = calc_channel_gains(angle)

    # 距离衰减：按声音类型用不同曲线
    # 真实源级别差约 120dB（枪声峰值 ~140dB vs 脚步 ~20dB），这里压成 base 0.45 vs 1.0
    # 可听距离：脚步约 25m / 枪声约 450m（以下 distance 0~1 是可调旋钮，非真实米数）
    distance = max(0.0, min(1.0, distance))
    if sound_type == 'footstep':
        # 脚步：平缓近距曲线，衰减快
        base = 0.45
        atten = 1.0 - 0.7 * distance
    else:
        # 枪声：反距离曲线，衰减慢（传播远）
        base = 1.0
        d0 = 0.02
        atten = d0 / (d0 + distance * (1.0 - d0))
    volume = base * atten
    source *= volume

    # 扩展到 8 声道
    n_samples = len(source)
    signal_71 = np.zeros((n_samples, 8), dtype=np.float32)

    for ch in range(8):
        signal_71[:, ch] = source * gains[ch]

    return signal_71


def generate_footstep_sequence(angle, distance=0.5, step_count=5, step_interval=0.4, sample_rate=SAMPLE_RATE):
    """
    生成连续脚步声序列
    
    参数:
        angle: 方向
        distance: 距离
        step_count: 步数
        step_interval: 步间间隔（秒）
    """
    step = generate_71_signal('footstep', angle, distance, sample_rate=sample_rate)
    interval_samples = int(step_interval * sample_rate)
    silence = np.zeros((interval_samples, 8), dtype=np.float32)

    parts = []
    for i in range(step_count):
        # 每一步音量略有不同（模拟真实脚步变化
        volume_var = 0.85 + np.random.rand() * 0.3
        parts.append(step * volume_var)
        if i < step_count - 1:
            parts.append(silence.copy())

    return np.vstack(parts, axis=0)
