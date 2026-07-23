"""
Echo Compass - 声音分类器
区分脚步声和枪声（通用信号特征，无需训练）
"""

import numpy as np

SAMPLE_RATE = 48000


def spectral_centroid(audio, sample_rate=SAMPLE_RATE):
    """
    计算频谱质心（频谱的"重心"频率）
    
    脚步声：质心低（~200-400Hz）
    枪声：质心高（~1000-3000Hz）
    """
    if len(audio.shape) > 1:
        # 多声道的话，先混合成单声道
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    # FFT
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sample_rate)
    
    total = np.sum(fft)
    if total < 1e-10:
        return 0
    
    centroid = np.sum(freqs * fft) / total
    return centroid


def high_freq_ratio(audio, sample_rate=SAMPLE_RATE, cutoff=2000):
    """
    计算高频能量占比
    
    脚步声：高频少（<20%）
    枪声：高频多（>40%）
    """
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sample_rate)
    
    total_energy = np.sum(fft**2)
    if total_energy < 1e-10:
        return 0
    
    high_energy = np.sum(fft[freqs >= cutoff]**2)
    return high_energy / total_energy


def attack_time(audio, sample_rate=SAMPLE_RATE):
    """
    计算起始时间（attack time）
    
    脚步声：起始慢（10-30ms）
    枪声：起始极快（1-3ms）
    """
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    # 包络（取绝对值的滑动最大值）
    envelope = np.abs(audio)
    window = max(1, int(sample_rate * 0.001))  # 1ms 窗口
    kernel = np.ones(window) / window
    envelope = np.convolve(envelope, kernel, mode='same')
    
    max_val = np.max(envelope)
    if max_val < 1e-10:
        return 0
    
    # 找到从 10% 上升到 90% 的时间
    threshold_high = max_val * 0.9
    threshold_low = max_val * 0.1
    
    # 找第一个超过 10% 的点
    start_idx = np.argmax(envelope > threshold_low)
    # 找第一个超过 90% 的点
    peak_idx = np.argmax(envelope > threshold_high)
    
    if peak_idx <= start_idx:
        # 直接从峰值开始
        start_idx = np.argmax(envelope > threshold_high * 0.5)
        peak_idx = np.argmax(envelope == max_val)
    
    attack_samples = peak_idx - start_idx
    attack_ms = attack_samples / sample_rate * 1000
    
    return max(0.1, attack_ms)


def duration_ms(audio, sample_rate=SAMPLE_RATE):
    """
    计算声音持续时间（从超过阈值到低于阈值）
    """
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    envelope = np.abs(audio)
    window = max(1, int(sample_rate * 0.002))
    kernel = np.ones(window) / window
    envelope = np.convolve(envelope, kernel, mode='same')
    
    max_val = np.max(envelope)
    if max_val < 1e-10:
        return 0
    
    threshold = max_val * 0.1
    
    above = envelope > threshold
    if not np.any(above):
        return 0
    
    start = np.argmax(above)
    # 从后往前找
    end = len(above) - 1 - np.argmax(above[::-1])
    
    duration = (end - start) / sample_rate * 1000
    return max(1.0, duration)


def zero_crossing_rate(audio, sample_rate=SAMPLE_RATE):
    """
    过零率（每秒过零次数）
    
    噪声多的声音（枪声）过零率高
    低频为主的声音（脚步声）过零率低
    """
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) < 2:
        return 0
    
    crossings = np.sum(np.abs(np.diff(np.sign(audio)))) / 2
    zcr = crossings / (len(audio) / sample_rate)
    return zcr


def classify_sound(audio, sample_rate=SAMPLE_RATE):
    """
    声音分类：脚步 vs 枪声 vs 其他
    
    参数:
        audio: (n_samples,) 或 (n_samples, n_channels) 音频数据
        sample_rate: 采样率
    
    返回:
        dict: {
            'type': 'footstep' | 'gunshot' | 'other' | 'silence',
            'confidence': 0~1,
            'features': { 特征值 },
        }
    """
    # 总能量
    if len(audio.shape) > 1:
        mono = np.mean(audio, axis=1)
    else:
        mono = audio
    
    rms = np.sqrt(np.mean(mono**2))
    
    if rms < 0.001:
        return {
            'type': 'silence',
            'confidence': 1.0,
            'features': {},
        }
    
    # 计算特征
    centroid = spectral_centroid(mono, sample_rate)
    high_ratio = high_freq_ratio(mono, sample_rate)
    attack = attack_time(mono, sample_rate)
    dur = duration_ms(mono, sample_rate)
    zcr = zero_crossing_rate(mono, sample_rate)
    
    features = {
        'spectral_centroid_hz': centroid,
        'high_freq_ratio': high_ratio,
        'attack_ms': attack,
        'duration_ms': dur,
        'zero_crossing_rate': zcr,
        'rms': rms,
    }
    
    # 简单的评分系统
    footstep_score = 0.0
    gunshot_score = 0.0
    
    # 频谱质心：低 = 脚步，高 = 枪声
    if centroid < 500:
        footstep_score += 2.0
    elif centroid < 800:
        footstep_score += 1.0
    elif centroid > 1500:
        gunshot_score += 2.0
    elif centroid > 1000:
        gunshot_score += 1.0
    
    # 高频占比：低 = 脚步，高 = 枪声
    if high_ratio < 0.15:
        footstep_score += 2.0
    elif high_ratio < 0.3:
        footstep_score += 1.0
    elif high_ratio > 0.4:
        gunshot_score += 2.0
    elif high_ratio > 0.25:
        gunshot_score += 1.0
    
    # 起始时间：慢 = 脚步，快 = 枪声
    if attack > 8:
        footstep_score += 2.0
    elif attack > 4:
        footstep_score += 1.0
    elif attack < 3:
        gunshot_score += 2.0
    elif attack < 5:
        gunshot_score += 1.0
    
    # 过零率：低 = 脚步，高 = 枪声
    if zcr < 800:
        footstep_score += 1.0
    elif zcr > 1500:
        gunshot_score += 1.0
    
    # 持续时间：脚步一般 100-300ms，枪声 50-200ms 但有尾巴
    if 80 < dur < 350:
        footstep_score += 0.5
    if 30 < dur < 250:
        gunshot_score += 0.5
    
    # 决定分类
    total_score = footstep_score + gunshot_score
    
    if total_score < 1.0:
        sound_type = 'other'
        confidence = 0.5
    elif footstep_score > gunshot_score * 1.5:
        sound_type = 'footstep'
        confidence = min(1.0, footstep_score / total_score)
    elif gunshot_score > footstep_score * 1.5:
        sound_type = 'gunshot'
        confidence = min(1.0, gunshot_score / total_score)
    else:
        sound_type = 'other'
        confidence = 0.5
    
    return {
        'type': sound_type,
        'confidence': confidence,
        'features': features,
    }
