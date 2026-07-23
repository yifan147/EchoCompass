"""
Echo Compass - 屏幕边缘8方位显示
多维度信息可视化：方向、强弱、远近
"""

import tkinter as tk
import math

from .protocol import CompassData, SOUND_TYPE_FOOTSTEP, SOUND_TYPE_GUNSHOT, SOUND_TYPE_OTHER


COLORS = {
    'footstep': '#58a6ff',
    'gunshot': '#f85149',
    'other': '#d2a8ff',
}


class ScreenOverlay(tk.Toplevel):
    """
    屏幕边缘8方位光晕显示窗口
    
    多维度可视化：
    - 方向：光晕在屏幕边缘对应位置亮起
    - 强弱：光晕大小和亮度体现
    - 远近：颜色深浅体现（深=近，浅=远）
    
    特性：
    - 全屏透明无边框，不遮挡中央视野
    - 多层光晕效果，渐变色透明
    - 自动跟随屏幕分辨率
    """
    
    DIRECTIONS = [
        {'name': '前', 'angle': 0, 'side': 'top', 'pos': 0.5},
        {'name': '前右', 'angle': 45, 'side': 'top', 'pos': 0.75},
        {'name': '右', 'angle': 90, 'side': 'right', 'pos': 0.5},
        {'name': '后右', 'angle': 135, 'side': 'bottom', 'pos': 0.75},
        {'name': '后', 'angle': 180, 'side': 'bottom', 'pos': 0.5},
        {'name': '后左', 'angle': 225, 'side': 'bottom', 'pos': 0.25},
        {'name': '左', 'angle': 270, 'side': 'left', 'pos': 0.5},
        {'name': '前左', 'angle': 315, 'side': 'top', 'pos': 0.25},
    ]
    
    MAX_GLOW_RADIUS = 80
    MIN_GLOW_RADIUS = 20
    FADE_DECAY = 0.82
    
    def __init__(self, master=None):
        super().__init__(master)
        self._init_window()
        self._sources = []
        self._canvas = None
        self._draw()
    
    def _init_window(self):
        self.overrideredirect(True)
        self.attributes('-transparentcolor', '#000001')
        self.attributes('-topmost', True)
        self.attributes('-alpha', 0.9)
        
        self.geometry(f"{self.winfo_screenwidth()}x{self.winfo_screenheight()}+0+0")
        self.configure(bg='#000001')
        
        self.update_idletasks()
    
    def _draw(self):
        if self._canvas:
            self._canvas.destroy()
        
        width = self.winfo_screenwidth()
        height = self.winfo_screenheight()
        
        self._canvas = tk.Canvas(self, width=width, height=height,
                                 bg='#000001', highlightthickness=0)
        self._canvas.pack(fill='both', expand=True)
        
        self._redraw()
    
    def _redraw(self):
        self._canvas.delete('glow')
        
        width = self.winfo_screenwidth()
        height = self.winfo_screenheight()
        
        for src in self._sources:
            if src['energy'] <= 0.01:
                continue
            
            sound_type = src['sound_type']
            base_color = COLORS.get(sound_type == SOUND_TYPE_GUNSHOT and 'gunshot' or
                                  sound_type == SOUND_TYPE_FOOTSTEP and 'footstep' or 'other')
            
            distance_factor = src['distance_factor']
            energy = src['energy']
            
            glow_size = self.MIN_GLOW_RADIUS + (self.MAX_GLOW_RADIUS - self.MIN_GLOW_RADIUS) * energy
            glow_size = int(glow_size)
            
            brightness = min(0.9, max(0.15, energy * 0.8 + distance_factor * 0.4))
            
            dir_idx = self._angle_to_index(src['angle'])
            dir_info = self.DIRECTIONS[dir_idx]
            side = dir_info['side']
            pos = dir_info['pos']
            
            if side == 'top':
                x = int(width * pos)
                y = 3
            elif side == 'bottom':
                x = int(width * pos)
                y = height - 3
            elif side == 'left':
                x = 3
                y = int(height * pos)
            else:
                x = width - 3
                y = int(height * pos)
            
            num_layers = 4
            for layer in range(num_layers):
                layer_ratio = (layer + 1) / num_layers
                layer_radius = int(glow_size * layer_ratio)
                layer_alpha = brightness * (1.0 - layer_ratio * 0.6)
                
                if layer_alpha < 0.05:
                    continue
                
                color = self._adjust_color_alpha(base_color, layer_alpha)
                
                if layer == 0:
                    line_width = max(2, int(4 * energy))
                else:
                    line_width = max(1, int(2 * layer_ratio))
                
                if side == 'top' or side == 'bottom':
                    self._canvas.create_oval(
                        x - layer_radius, y - layer_radius * 0.3,
                        x + layer_radius, y + layer_radius * 0.3,
                        fill='', outline=color, width=line_width,
                        tags='glow'
                    )
                else:
                    self._canvas.create_oval(
                        x - layer_radius * 0.3, y - layer_radius,
                        x + layer_radius * 0.3, y + layer_radius,
                        fill='', outline=color, width=line_width,
                        tags='glow'
                    )
            
            core_radius = max(4, int(8 * energy))
            core_color = self._adjust_color_alpha(base_color, brightness * 1.1)
            self._canvas.create_oval(
                x - core_radius, y - core_radius,
                x + core_radius, y + core_radius,
                fill=core_color, outline='',
                tags='glow'
            )
    
    def _adjust_color_alpha(self, hex_color, alpha):
        hex_color = hex_color.lstrip('#')
        r = int(hex_color[0:2], 16)
        g = int(hex_color[2:4], 16)
        b = int(hex_color[4:6], 16)
        
        r = int(r * alpha)
        g = int(g * alpha)
        b = int(b * alpha)
        
        return f'#{r:02x}{g:02x}{b:02x}'
    
    def _angle_to_index(self, angle):
        while angle < 0:
            angle += 360
        while angle >= 360:
            angle -= 360
        idx = int((angle + 22.5) % 360 // 45)
        return idx
    
    def update_data(self, data: CompassData):
        now = tk._time()
        
        if data.has_sound:
            idx = self._angle_to_index(data.angle)
            
            distance_factor = 1.0 - data.distance
            
            found = False
            for src in self._sources:
                if self._angle_to_index(src['angle']) == idx:
                    src['energy'] = max(src['energy'], data.energy)
                    src['distance_factor'] = max(src['distance_factor'], distance_factor)
                    src['sound_type'] = data.sound_type
                    src['angle'] = data.angle
                    src['last_update'] = now
                    found = True
                    break
            
            if not found:
                self._sources.append({
                    'angle': data.angle,
                    'energy': data.energy,
                    'distance_factor': distance_factor,
                    'sound_type': data.sound_type,
                    'last_update': now,
                })
        
        self._sources = [src for src in self._sources if now - src['last_update'] < 1.0]
        
        for src in self._sources:
            src['energy'] *= self.FADE_DECAY
        
        self._redraw()
    
    def show(self):
        self.deiconify()
    
    def hide(self):
        self.withdraw()