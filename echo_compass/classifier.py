"""
Echo Compass - 声音分类器
区分脚步声和枪声（基于频谱+时域特征的混合分类器）
"""

import numpy as np

SAMPLE_RATE = 48000


def spectral_centroid(audio, sample_rate=SAMPLE_RATE):
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sample_rate)
    
    total = np.sum(fft)
    if total < 1e-10:
        return 0
    
    centroid = np.sum(freqs * fft) / total
    return centroid


def spectral_flatness(audio, sample_rate=SAMPLE_RATE):
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    fft = np.abs(np.fft.rfft(audio))
    fft = np.maximum(fft, 1e-10)
    
    geometric_mean = np.exp(np.mean(np.log(fft)))
    arithmetic_mean = np.mean(fft)
    
    if arithmetic_mean < 1e-10:
        return 0
    
    return geometric_mean / arithmetic_mean


def spectral_bandwidth(audio, sample_rate=SAMPLE_RATE):
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sample_rate)
    
    total = np.sum(fft)
    if total < 1e-10:
        return 0
    
    centroid = np.sum(freqs * fft) / total
    
    variance = np.sum(fft * (freqs - centroid) ** 2) / total
    return np.sqrt(variance)


def high_freq_ratio(audio, sample_rate=SAMPLE_RATE, cutoff=2000):
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


def mid_freq_ratio(audio, sample_rate=SAMPLE_RATE, low=500, high=2000):
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sample_rate)
    
    total_energy = np.sum(fft**2)
    if total_energy < 1e-10:
        return 0
    
    mid_mask = (freqs >= low) & (freqs < high)
    mid_energy = np.sum(fft[mid_mask]**2)
    return mid_energy / total_energy


def attack_time(audio, sample_rate=SAMPLE_RATE):
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    envelope = np.abs(audio)
    window = max(1, int(sample_rate * 0.001))
    kernel = np.ones(window) / window
    envelope = np.convolve(envelope, kernel, mode='same')
    
    max_val = np.max(envelope)
    if max_val < 1e-10:
        return 0
    
    threshold_high = max_val * 0.9
    threshold_low = max_val * 0.1
    
    start_idx = np.argmax(envelope > threshold_low)
    
    above_high = envelope > threshold_high
    if np.any(above_high):
        peak_idx = np.argmax(above_high)
    else:
        peak_idx = np.argmax(envelope == max_val)
    
    if peak_idx <= start_idx:
        start_idx = np.argmax(envelope > threshold_high * 0.5)
        peak_idx = np.argmax(envelope == max_val)
    
    attack_samples = peak_idx - start_idx
    attack_ms = attack_samples / sample_rate * 1000
    
    return max(0.1, attack_ms)


def duration_ms(audio, sample_rate=SAMPLE_RATE):
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
    end = len(above) - 1 - np.argmax(above[::-1])
    
    duration = (end - start) / sample_rate * 1000
    return max(1.0, duration)


def zero_crossing_rate(audio, sample_rate=SAMPLE_RATE):
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) < 2:
        return 0
    
    crossings = np.sum(np.abs(np.diff(np.sign(audio)))) / 2
    zcr = crossings / (len(audio) / sample_rate)
    return zcr


def peak_to_rms_ratio(audio):
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    peak = np.max(np.abs(audio))
    rms = np.sqrt(np.mean(audio**2))
    
    if rms < 1e-10:
        return 0
    
    return peak / rms


def spectral_rolloff(audio, sample_rate=SAMPLE_RATE, fraction=0.85):
    if len(audio.shape) > 1:
        audio = np.mean(audio, axis=1)
    
    if len(audio) == 0:
        return 0
    
    fft = np.abs(np.fft.rfft(audio))
    freqs = np.fft.rfftfreq(len(audio), 1.0 / sample_rate)
    
    total_energy = np.sum(fft**2)
    if total_energy < 1e-10:
        return 0
    
    cumulative = np.cumsum(fft**2)
    target = total_energy * fraction
    
    idx = np.argmax(cumulative >= target)
    return freqs[idx]


def classify_sound(audio, sample_rate=SAMPLE_RATE):
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
    
    centroid = spectral_centroid(mono, sample_rate)
    high_ratio = high_freq_ratio(mono, sample_rate)
    mid_ratio = mid_freq_ratio(mono, sample_rate)
    attack = attack_time(mono, sample_rate)
    dur = duration_ms(mono, sample_rate)
    zcr = zero_crossing_rate(mono, sample_rate)
    flatness = spectral_flatness(mono, sample_rate)
    p2r = peak_to_rms_ratio(mono)
    bandwidth = spectral_bandwidth(mono, sample_rate)
    rolloff = spectral_rolloff(mono, sample_rate)
    
    features = {
        'spectral_centroid_hz': centroid,
        'high_freq_ratio': high_ratio,
        'mid_freq_ratio': mid_ratio,
        'attack_ms': attack,
        'duration_ms': dur,
        'zero_crossing_rate': zcr,
        'spectral_flatness': flatness,
        'peak_to_rms': p2r,
        'spectral_bandwidth': bandwidth,
        'spectral_rolloff': rolloff,
        'rms': rms,
    }
    
    footstep_score = 0.0
    gunshot_score = 0.0
    
    # 频谱质心
    if centroid < 400:
        footstep_score += 2.5
    elif centroid < 700:
        footstep_score += 1.2
    elif centroid > 2000:
        gunshot_score += 2.5
    elif centroid > 1200:
        gunshot_score += 1.5
    elif centroid > 800:
        gunshot_score += 0.8
    
    # 高频占比
    if high_ratio < 0.12:
        footstep_score += 2.5
    elif high_ratio < 0.25:
        footstep_score += 1.2
    elif high_ratio > 0.45:
        gunshot_score += 2.5
    elif high_ratio > 0.35:
        gunshot_score += 1.5
    elif high_ratio > 0.25:
        gunshot_score += 0.8
    
    # 中频占比（脚步声中频能量高）
    if mid_ratio > 0.4:
        footstep_score += 1.5
    elif mid_ratio > 0.25:
        footstep_score += 0.8
    if mid_ratio < 0.2:
        gunshot_score += 1.0
    
    # 起始时间
    if attack > 10:
        footstep_score += 2.5
    elif attack > 5:
        footstep_score += 1.5
    elif attack < 2.5:
        gunshot_score += 2.5
    elif attack < 4:
        gunshot_score += 1.5
    elif attack < 6:
        gunshot_score += 0.5
    
    # 过零率
    if zcr < 600:
        footstep_score += 1.5
    elif zcr < 1000:
        footstep_score += 0.5
    elif zcr > 2000:
        gunshot_score += 2.0
    elif zcr > 1400:
        gunshot_score += 1.2
    elif zcr > 1000:
        gunshot_score += 0.5
    
    # 频谱平坦度（枪声更接近白噪声，平坦度高）
    if flatness > 0.25:
        gunshot_score += 1.5
    elif flatness > 0.15:
        gunshot_score += 0.8
    if flatness < 0.1:
        footstep_score += 1.0
    
    # 峰值/RMS比（枪声峰值尖锐）
    if p2r > 8:
        gunshot_score += 1.5
    elif p2r > 5:
        gunshot_score += 0.8
    if p2r < 3:
        footstep_score += 1.0
    
    # 频谱带宽
    if bandwidth > 3000:
        gunshot_score += 1.5
    elif bandwidth > 1500:
        gunshot_score += 0.8
    if bandwidth < 800:
        footstep_score += 1.0
    
    # 频谱滚降
    if rolloff > 4000:
        gunshot_score += 1.5
    elif rolloff > 2500:
        gunshot_score += 0.8
    if rolloff < 1500:
        footstep_score += 1.0
    
    # 持续时间
    if 80 < dur < 400:
        footstep_score += 1.0
    if 30 < dur < 200:
        gunshot_score += 0.8
    if dur > 400:
        footstep_score += 0.5
    if dur < 30:
        gunshot_score += 0.5
    
    total_score = footstep_score + gunshot_score
    
    if total_score < 2.0:
        sound_type = 'other'
        confidence = 0.3
    elif footstep_score > gunshot_score * 1.4:
        sound_type = 'footstep'
        confidence = min(1.0, footstep_score / total_score)
    elif gunshot_score > footstep_score * 1.4:
        sound_type = 'gunshot'
        confidence = min(1.0, gunshot_score / total_score)
    else:
        sound_type = 'other'
        confidence = 0.4 + abs(footstep_score - gunshot_score) / (total_score + 1e-10) * 0.3
    
    return {
        'type': sound_type,
        'confidence': confidence,
        'features': features,
    }