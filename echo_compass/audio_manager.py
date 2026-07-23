"""
Echo Compass - 音频设备管理器
自动检测并适配系统音频输出与耳机设备
支持多声道捕获和虚拟7.1解码
"""

import numpy as np


class AudioDeviceManager:
    """
    音频设备管理器
    
    功能：
    - 自动检测系统音频设备（扬声器、耳机、麦克风）
    - 识别最佳loopback捕获设备
    - 支持多声道音频捕获（立体声/5.1/7.1）
    - 提供设备选择和配置功能
    """
    
    def __init__(self):
        self._soundcard = None
        self._devices = []
        self._selected_device = None
        self._is_initialized = False
    
    def initialize(self):
        """初始化音频设备管理器"""
        try:
            import soundcard as sc
            self._soundcard = sc
            self._scan_devices()
            self._is_initialized = True
            return True
        except ImportError:
            return False
        except Exception:
            return False
    
    def _scan_devices(self):
        """扫描所有音频设备"""
        self._devices = []
        
        try:
            all_mics = self._soundcard.all_microphones(include_loopback=True)
            
            for device in all_mics:
                self._devices.append({
                    'name': device.name,
                    'id': device.id,
                    'is_loopback': device.isloopback,
                    'channels': device.channels,
                    'samplerate': device.samplerate,
                    'is_default_speaker': False,
                    'device_obj': device,
                })
            
            try:
                default_speaker = self._soundcard.default_speaker()
                for dev in self._devices:
                    if dev['name'] == default_speaker.name:
                        dev['is_default_speaker'] = True
                        break
            except Exception:
                pass
        except Exception:
            pass
    
    def get_devices(self):
        """获取所有检测到的设备"""
        return self._devices
    
    def get_loopback_devices(self):
        """获取所有loopback设备"""
        return [d for d in self._devices if d['is_loopback']]
    
    def get_best_device(self):
        """自动选择最佳设备"""
        loopback_devices = self.get_loopback_devices()
        
        if not loopback_devices:
            return None
        
        try:
            default_speaker = self._soundcard.default_speaker()
            
            for dev in loopback_devices:
                if dev['is_default_speaker']:
                    return dev
        except Exception:
            pass
        
        for dev in loopback_devices:
            if 'headphone' in dev['name'].lower() or '耳机' in dev['name']:
                return dev
        
        for dev in loopback_devices:
            if dev['channels'] >= 2:
                return dev
        
        return loopback_devices[0] if loopback_devices else None
    
    def select_device(self, device_id):
        """选择指定设备"""
        for dev in self._devices:
            if dev['id'] == device_id:
                self._selected_device = dev
                return True
        return False
    
    def get_selected_device(self):
        """获取当前选中的设备"""
        return self._selected_device
    
    def create_recorder(self, sample_rate=48000, block_ms=10):
        """创建音频录制器"""
        if not self._is_initialized:
            return None
        
        if self._selected_device is None:
            self._selected_device = self.get_best_device()
        
        if self._selected_device is None:
            return None
        
        blocksize = int(sample_rate * block_ms / 1000)
        
        try:
            return self._selected_device['device_obj'].recorder(
                samplerate=sample_rate,
                channels=self._selected_device['channels'],
                blocksize=blocksize
            )
        except Exception:
            return None
    
    def get_device_info(self):
        """获取设备信息"""
        if self._selected_device is None:
            return None
        
        return {
            'name': self._selected_device['name'],
            'channels': self._selected_device['channels'],
            'samplerate': self._selected_device['samplerate'],
            'is_loopback': self._selected_device['is_loopback'],
            'is_default_speaker': self._selected_device['is_default_speaker'],
        }


class Virtual71Decoder:
    """
    虚拟7.1解码器
    
    将立体声/HRTF音频解码为8声道环绕声
    使用头部相关传递函数(HRTF)特征进行方向解码
    """
    
    CHANNEL_ANGLES = np.array([
        -30,   # FL 前左
        30,    # FR 前右
        0,     # FC 中置
        0,     # LFE
        -150,  # RL 后左
        150,   # RR 后右
        -90,   # SL 侧左
        90,    # SR 侧右
    ])
    
    def __init__(self):
        pass
    
    def decode_stereo_to_71(self, stereo_data, sample_rate=48000):
        """
        将立体声数据解码为7.1声道
        
        参数:
            stereo_data: (n_samples, 2) 立体声音频
            sample_rate: 采样率
        
        返回:
            (n_samples, 8) 7.1声道数据
        """
        n_samples = stereo_data.shape[0]
        output = np.zeros((n_samples, 8), dtype=np.float64)
        
        left = stereo_data[:, 0]
        right = stereo_data[:, 1]
        
        output[:, 0] = left * 0.8
        output[:, 1] = right * 0.8
        output[:, 2] = (left + right) * 0.3
        
        angle, confidence = self._estimate_direction(left, right, sample_rate)
        
        spread_width = 60
        for ch in range(8):
            ch_angle = self.CHANNEL_ANGLES[ch]
            
            angle_diff = np.abs(angle - ch_angle)
            angle_diff = min(angle_diff, 360 - angle_diff)
            
            if angle_diff < spread_width:
                weight = np.cos(np.radians(angle_diff)) ** 2
                if ch in [0, 1]:
                    output[:, ch] += left * weight * 0.5 if ch == 0 else right * weight * 0.5
        
        center_mix = (left + right) * 0.4
        output[:, 2] += center_mix
        
        return output
    
    def _estimate_direction(self, left, right, sample_rate=48000):
        """估计立体声方向"""
        e_left = np.sqrt(np.mean(left ** 2))
        e_right = np.sqrt(np.mean(right ** 2))
        
        if e_left + e_right < 1e-10:
            return 0.0, 0.0
        
        db_diff = 20 * np.log10((e_right + 1e-10) / (e_left + 1e-10))
        
        angle = db_diff * 8
        angle = np.clip(angle, -90, 90)
        
        confidence = min(1.0, abs(db_diff) / 10.0)
        
        return float(angle), float(confidence)
    
    def extract_channel_energies(self, audio_data):
        """提取各声道能量"""
        if audio_data.shape[1] == 8:
            return self._extract_8channel_energies(audio_data)
        elif audio_data.shape[1] == 2:
            decoded = self.decode_stereo_to_71(audio_data)
            return self._extract_8channel_energies(decoded)
        else:
            return self._extract_generic_energies(audio_data)
    
    def _extract_8channel_energies(self, audio_data):
        """从8声道数据提取能量"""
        energies = np.zeros(8)
        for ch in range(8):
            energies[ch] = np.sqrt(np.mean(audio_data[:, ch] ** 2))
        return energies
    
    def _extract_generic_energies(self, audio_data):
        """从通用多声道数据提取能量"""
        n_channels = audio_data.shape[1]
        energies = np.zeros(8)
        
        if n_channels == 6:
            energies[0] = np.sqrt(np.mean(audio_data[:, 0] ** 2))
            energies[1] = np.sqrt(np.mean(audio_data[:, 1] ** 2))
            energies[2] = np.sqrt(np.mean(audio_data[:, 2] ** 2))
            energies[5] = np.sqrt(np.mean(audio_data[:, 3] ** 2))
            energies[4] = np.sqrt(np.mean(audio_data[:, 4] ** 2))
            energies[6] = np.sqrt(np.mean(audio_data[:, 5] ** 2))
        else:
            mono = np.mean(audio_data, axis=1)
            energies[0] = np.sqrt(np.mean(mono ** 2))
            energies[1] = energies[0]
            energies[2] = energies[0]
        
        return energies


audio_manager = AudioDeviceManager()
virtual_decoder = Virtual71Decoder()