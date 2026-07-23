"""
Echo Compass - 方向与距离计算
支持两种模式:
  - 8声道 (7.1): 加权平均 / 波束成形
  - 双耳 (立体声): ILD(强度差) + ITD(时间差) 融合, 角度范围 ±90°
"""

import numpy as np

CHANNEL_NAMES = ["FL", "FR", "FC", "LFE", "RL", "RR", "SL", "SR"]

# 每个声道的角度（度）
CHANNEL_ANGLES = np.array([
    -30,    # FL 前左
    30,     # FR 前右
    0,      # FC 中置
    0,      # LFE（暂时忽略方向性）
    -150,   # RL 后左
    150,    # RR 后右
    -90,    # SL 侧左
    90,     # SR 侧右
])


def channel_energies(audio_block):
    """
    计算每个声道的 RMS 能量
    
    参数:
        audio_block: shape (n_samples, 8) 或 (n_samples, n_channels)
    
    返回:
        energies: shape (n_channels,) RMS能量值
    """
    if len(audio_block.shape) == 1:
        return np.array([np.sqrt(np.mean(audio_block**2))])
    
    n_channels = audio_block.shape[1]
    energies = np.zeros(n_channels)
    for ch in range(n_channels):
        energies[ch] = np.sqrt(np.mean(audio_block[:, ch]**2))
    return energies


def calc_direction_weighted(energies):
    """
    加权平均法计算方向
    
    原理：把每个声道的能量当作权重，角度当作位置，
         算出加权平均方向
    
    参数:
        energies: shape (8,) 每个声道的能量
    
    返回:
        angle: 方向角度（度），0=正前方，顺时针为正
               范围 [-180, 180]
        confidence: 置信度 0~1，能量越集中越高
    """
    n = min(len(energies), 8)
    
    # 排除 LFE（第3声道，全向）
    use_channels = [i for i in range(n) if i != 3]
    e = energies[use_channels]
    angles = CHANNEL_ANGLES[use_channels]
    
    total_energy = np.sum(e)
    
    if total_energy < 1e-8:
        return 0.0, 0.0
    
    # 转换为单位圆上的坐标
    x = np.sum(e * np.cos(np.radians(angles)))
    y = np.sum(e * np.sin(np.radians(angles)))
    
    # 计算方向角度
    angle = np.degrees(np.arctan2(y, x))
    
    # 置信度：合矢量长度 / 总能量
    # 如果全在一个方向，合矢量长度 ≈ 总能量 → 置信度高
    # 如果各个方向都有，合矢量长度 << 总能量 → 置信度低
    magnitude = np.sqrt(x**2 + y**2)
    confidence = min(1.0, magnitude / total_energy)
    
    return angle, confidence


def calc_direction_beamforming(energies):
    """
    波束成形法计算方向（更精确）
    
    原理：扫描 360° 每个角度，计算该方向的"波束功率"，
         功率最大的方向就是声源方向
    
    参数:
        energies: shape (8,) 每个声道的能量
    
    返回:
        angle: 方向角度（度）
        confidence: 置信度 0~1
    """
    n = min(len(energies), 8)
    
    use_channels = [i for i in range(n) if i != 3]
    e = energies[use_channels]
    angles = CHANNEL_ANGLES[use_channels]
    
    total_energy = np.sum(e)
    
    if total_energy < 1e-8:
        return 0.0, 0.0
    
    # 扫描 0~360 度，每 1 度一个采样
    test_angles = np.linspace(-180, 180, 361)
    beam_power = np.zeros_like(test_angles)
    
    for i, theta in enumerate(test_angles):
        # 每个声道的"对齐程度"：角度差越小，贡献越大
        diffs = np.abs(test_angle_diff(angles, theta))
        # 余弦加权
        weights = np.cos(np.radians(diffs))
        weights = np.maximum(0, weights)
        beam_power[i] = np.sum(e * weights)
    
    # 找最大功率的角度
    max_idx = np.argmax(beam_power)
    angle = test_angles[max_idx]
    
    # 置信度：最大功率 / 总功率
    confidence = beam_power[max_idx] / total_energy
    confidence = min(1.0, max(0.0, confidence))
    
    return angle, confidence


def test_angle_diff(a, b):
    """计算两个角度的差（-180~180）"""
    diff = a - b
    return (diff + 180) % 360 - 180


def calc_distance(energies):
    """
    估计距离（相对值）
    
    基于：
    1. 总能量（越大越近）
    2. 直接声/混响比（暂时只用总能量）
    3. 高频占比（越远高频越少）
    
    参数:
        energies: shape (8,) 每个声道的能量
    
    返回:
        distance: 0~1，0=最近，1=最远
        total_energy: 总能量（用于后续判断是否有声音）
    """
    total_energy = np.sum(energies)
    
    if total_energy < 1e-8:
        return 1.0, 0.0
    
    # 简单的对数映射
    # 假设最大可检测能量约为 0.5（满幅 1.0 算很近了）
    # 用 dB 来做更线性的映射
    db = 20 * np.log10(total_energy + 1e-10)
    
    # 把 -60dB ~ 0dB 映射到 1~0
    distance = np.clip((-db) / 60.0, 0.0, 1.0)
    
    return distance, total_energy


def has_sound(energies, threshold_db=-40):
    """
    判断是否有显著声音
    
    参数:
        energies: 声道能量
        threshold_db: 阈值（dB）
    
    返回:
        bool: 是否有声音
    """
    total = np.sum(energies)
    if total < 1e-10:
        return False
    db = 20 * np.log10(total)
    return db > threshold_db


def analyze_audio_block(audio_block, method='weighted'):
    """
    分析一个音频块，输出完整结果
    
    参数:
        audio_block: (n_samples, n_channels) 音频数据
        method: 'weighted' 或 'beamforming' (仅对 8 声道有效)
    
    返回:
        dict: {
            'has_sound': bool,
            'angle': float,  # 度
            'distance': float,  # 0~1
            'confidence': float,  # 0~1
            'total_energy': float,
            'energies': array(n_channels,),
        }
    """
    energies = channel_energies(audio_block)
    
    sound = has_sound(energies)
    
    if not sound:
        return {
            'has_sound': False,
            'angle': 0.0,
            'distance': 1.0,
            'confidence': 0.0,
            'total_energy': 0.0,
            'energies': energies,
        }
    
    n_channels = audio_block.shape[1] if len(audio_block.shape) > 1 else 1
    
    front_back = 0.0
    
    if n_channels == 2:
        angle, confidence = calc_direction_binaural(audio_block)
        front_back = _detect_front_back(audio_block)
    elif method == 'beamforming':
        angle, confidence = calc_direction_beamforming(energies)
    else:
        angle, confidence = calc_direction_weighted(energies)
    
    distance, total_energy = calc_distance(energies)
    
    return {
        'has_sound': True,
        'angle': float(angle),
        'distance': float(distance),
        'confidence': float(confidence),
        'total_energy': float(total_energy),
        'energies': energies,
        'front_back': float(front_back),
    }


# ========== 双耳方向计算 (立体声 / HRTF 模式) ==========

# 人头半径 (米), 用于 ITD → 角度换算
HEAD_RADIUS = 0.0875
# 声速 (m/s)
SPEED_OF_SOUND = 343.0
# 最大 ITD (秒) = 人头直径 / 声速
MAX_ITD = 2 * HEAD_RADIUS / SPEED_OF_SOUND  # ≈ 0.00051 s

# ===== 可调参数（进游戏校）=====
# ILD 高通截止频率：只拿此频率以上的能量算左右响度差。
# 人耳分左右靠高频（头影效应），低频绕头走两耳差不多响，会稀释差值。
ILD_HIGHPASS_HZ = 1500
# ILD 每 1dB 响度差对应多少度，最多 ±90° 封顶。
ILD_DEG_PER_DB = 8
# 高频能量占全频段的最低比例，低于此值说明声音太闷（远距离），
# 退回全频段算 ILD 兜底，置信度降低。
ILD_HF_MIN_RATIO = 0.05


def _simple_highpass(signal, cutoff_hz, sample_rate):
    """简化的高通滤波：使用一阶差分近似，避免FFT的性能开销"""
    n = len(signal)
    if n < 2:
        return signal.astype(np.float64)
    result = np.zeros(n, dtype=np.float64)
    result[0] = signal[0]
    rc = 1.0 / (2 * np.pi * cutoff_hz / sample_rate)
    alpha = rc / (rc + 1.0)
    for i in range(1, n):
        result[i] = alpha * result[i-1] + alpha * (signal[i] - signal[i-1])
    return result


def _detect_reverberation(audio_block, sample_rate=48000):
    """检测混响：计算直达声与混响能量比"""
    if len(audio_block.shape) > 1:
        mono = np.mean(audio_block, axis=1)
    else:
        mono = audio_block
    
    n_samples = len(mono)
    
    onset_win = int(sample_rate * 0.005)
    tail_start = int(sample_rate * 0.015)
    
    if n_samples <= tail_start:
        return 0.0
    
    direct_energy = np.mean(mono[:onset_win] ** 2)
    tail_energy = np.mean(mono[tail_start:] ** 2)
    
    if direct_energy < 1e-10:
        return 1.0
    
    reverb_ratio = tail_energy / direct_energy
    return min(reverb_ratio, 3.0)


def _detect_clipping(audio_block):
    """检测削顶：信号是否接近最大幅值"""
    max_val = np.max(np.abs(audio_block))
    return max_val > 0.85


def _detect_front_back(audio_block, sample_rate=48000):
    """
    前后方向判断：基于 HRTF 频谱特征
    
    HRTF 前方特征：
    - 耳壳共振峰在 5-10kHz 区域明显
    - 高频衰减较小
    
    HRTF 后方特征：
    - 耳壳共振峰被抑制
    - 高频衰减更大
    - 频谱包络更平坦
    
    返回: 正=前方倾向, 负=后方倾向, 绝对值=置信度
    """
    if len(audio_block.shape) > 1:
        mono = np.mean(audio_block, axis=1)
    else:
        mono = audio_block
    
    n_samples = len(mono)
    if n_samples < 64:
        return 0.0
    
    fft = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(n_samples, 1.0 / sample_rate)
    
    front_score = 0.0
    back_score = 0.0
    
    # 5-8kHz 共振峰区域（前方更明显）
    mid_high_mask = (freqs >= 5000) & (freqs <= 8000)
    mid_high_energy = np.sum(fft[mid_high_mask] ** 2)
    
    # 8-12kHz 区域（前方更强）
    high_mask = (freqs >= 8000) & (freqs <= 12000)
    high_energy = np.sum(fft[high_mask] ** 2)
    
    # 2-4kHz 区域（参考基准）
    mid_mask = (freqs >= 2000) & (freqs <= 4000)
    mid_energy = np.sum(fft[mid_mask] ** 2)
    
    total_energy = np.sum(fft ** 2)
    
    if mid_energy < 1e-10 or total_energy < 1e-10:
        return 0.0
    
    # 前方特征：高频相对能量高
    high_ratio = high_energy / mid_energy
    mid_high_ratio = mid_high_energy / mid_energy
    
    # 计算频谱平坦度（后方更平坦）
    geometric_mean = np.exp(np.mean(np.log(np.maximum(fft[mid_high_mask], 1e-10))))
    arithmetic_mean = np.mean(fft[mid_high_mask])
    flatness = geometric_mean / arithmetic_mean if arithmetic_mean > 1e-10 else 0
    
    if high_ratio > 0.8:
        front_score += 2.0
    elif high_ratio > 0.5:
        front_score += 1.0
    
    if mid_high_ratio > 1.2:
        front_score += 1.5
    elif mid_high_ratio > 0.8:
        front_score += 0.5
    
    if flatness > 0.3:
        back_score += 1.5
    elif flatness > 0.2:
        back_score += 0.8
    
    if high_ratio < 0.3:
        back_score += 1.5
    
    score_diff = front_score - back_score
    max_score = max(front_score, back_score, 1.0)
    
    return score_diff / max_score


def calc_direction_binaural(audio_block, sample_rate=48000, onset_window_ms=3):
    """
    双耳方向计算：高频 ILD 为主，增加反射/混响/削顶检测

    参数:
        audio_block: (n_samples, 2) 立体声音频
        sample_rate: 采样率
        onset_window_ms: 起音后取多少毫秒用于方向计算

    返回:
        angle: 方向角度（度），0=正前，-90=正左，+90=正右
        confidence: 置信度 0~1
    """
    if len(audio_block.shape) == 1 or audio_block.shape[1] < 2:
        return 0.0, 0.0

    left = audio_block[:, 0].astype(np.float64)
    right = audio_block[:, 1].astype(np.float64)

    n_samples = len(left)

    is_clipped = _detect_clipping(audio_block)
    reverb_ratio = _detect_reverberation(audio_block, sample_rate)

    # ---- 找起音点 ----
    win_size = max(1, sample_rate // 1000)
    n_windows = n_samples // win_size

    onset_idx = 0
    if n_windows >= 2:
        energies = np.zeros(n_windows)
        for i in range(n_windows):
            s = i * win_size
            e = s + win_size
            energies[i] = np.sqrt(np.mean(left[s:e]**2 + right[s:e]**2))

        avg_e = np.mean(energies[:max(1, n_windows//4)])
        threshold = max(avg_e * 3, 1e-6)

        for i in range(n_windows):
            if energies[i] > threshold:
                onset_idx = i * win_size
                break

    # ---- 只取起音后小窗口 ----
    window_samples = int(sample_rate * onset_window_ms / 1000)
    end_idx = min(onset_idx + window_samples, n_samples)

    if end_idx - onset_idx < win_size:
        onset_idx = 0
        end_idx = n_samples

    left_win = left[onset_idx:end_idx]
    right_win = right[onset_idx:end_idx]

    if len(left_win) < 4:
        return 0.0, 0.0

    # ---- ILD: 高频强度差 ----
    e_left_full = np.sqrt(np.mean(left_win ** 2))
    e_right_full = np.sqrt(np.mean(right_win ** 2))
    full_energy = e_left_full + e_right_full

    if full_energy < 1e-10:
        return 0.0, 0.0

    left_hp = _simple_highpass(left_win, ILD_HIGHPASS_HZ, sample_rate)
    right_hp = _simple_highpass(right_win, ILD_HIGHPASS_HZ, sample_rate)
    e_left_hp = np.sqrt(np.mean(left_hp ** 2))
    e_right_hp = np.sqrt(np.mean(right_hp ** 2))
    hf_energy = e_left_hp + e_right_hp

    hf_ratio = hf_energy / (full_energy + 1e-10)
    use_hf = hf_ratio >= ILD_HF_MIN_RATIO

    if use_hf:
        e_left_use = e_left_hp
        e_right_use = e_right_hp
    else:
        e_left_use = e_left_full
        e_right_use = e_right_full

    db_left = 20 * np.log10(e_left_use + 1e-10)
    db_right = 20 * np.log10(e_right_use + 1e-10)
    db_diff = db_right - db_left

    angle = float(np.clip(db_diff * ILD_DEG_PER_DB, -90.0, 90.0))

    # ---- 置信度 ----
    confidence = min(1.0, abs(db_diff) / 10.0)

    if not use_hf:
        confidence *= 0.6

    if is_clipped:
        confidence *= 0.4

    if reverb_ratio > 1.5:
        confidence *= max(0.3, 1.0 - (reverb_ratio - 1.0) * 0.3)

    if abs(db_diff) < 2:
        confidence *= 0.5

    return float(angle), float(confidence)
