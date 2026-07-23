"""
Echo Compass - tkinter 罗盘 UI
电脑端显示用，和硬件端显示逻辑保持一致
"""

import tkinter as tk
import math
import time

from .protocol import CompassData, SOUND_TYPE_NAMES, SOUND_TYPE_FOOTSTEP, SOUND_TYPE_GUNSHOT, SOUND_TYPE_OTHER


# 颜色配置（深色主题）
COLORS = {
    'bg': '#0d1117',
    'compass_bg': '#161b22',
    'compass_ring': '#30363d',
    'compass_grid': '#21262d',
    'text': '#c9d1d9',
    'text_dim': '#8b949e',
    'footstep': '#58a6ff',      # 蓝色 = 脚步
    'gunshot': '#f85149',       # 红色 = 枪声
    'other': '#d2a8ff',         # 紫色 = 其他
    'direction_indicator': '#58a6ff',
}


class EdgeDisplay(tk.Canvas):
    """
    屏幕上边缘 8 方位显示条
    
    8 个方位：前、前右、右、后右、后、后左、左、前左
    根据声音强弱动态显示条形高度，颜色区分声音类型
    """
    
    DIRECTIONS = [
        {'name': '前', 'angle': 0},
        {'name': '前右', 'angle': 45},
        {'name': '右', 'angle': 90},
        {'name': '后右', 'angle': 135},
        {'name': '后', 'angle': 180},
        {'name': '后左', 'angle': 225},
        {'name': '左', 'angle': 270},
        {'name': '前左', 'angle': 315},
    ]
    
    def __init__(self, parent, height=60, **kwargs):
        super().__init__(parent, height=height, bg=COLORS['bg'], 
                         highlightthickness=0, **kwargs)
        self.height = height
        self._current_data = CompassData()
        self._energy_history = [0.0] * 8
        self._draw_static()
    
    def _draw_static(self):
        """画静态元素"""
        self.delete('all')
        width = self.winfo_width()
        if width <= 0:
            width = 400
        
        bar_width = width // len(self.DIRECTIONS)
        gap = 2
        
        for i, dir_info in enumerate(self.DIRECTIONS):
            x = i * bar_width
            self.create_text(x + bar_width // 2, self.height - 10,
                            text=dir_info['name'], fill=COLORS['text_dim'],
                            font=('Arial', 8))
    
    def _angle_to_index(self, angle):
        """将角度（0~360）映射到 8 个方位索引"""
        while angle < 0:
            angle += 360
        while angle >= 360:
            angle -= 360
        idx = int((angle + 22.5) % 360 // 45)
        return idx
    
    def update_data(self, data: CompassData):
        """更新显示数据"""
        self._current_data = data
        self._redraw()
    
    def _redraw(self):
        """重绘动态元素"""
        width = self.winfo_width()
        if width <= 0:
            width = 400
        
        bar_width = width // len(self.DIRECTIONS)
        gap = 2
        
        self.delete('bar')
        
        if self._current_data.has_sound:
            idx = self._angle_to_index(self._current_data.angle)
            energy = self._current_data.energy
            
            for i in range(len(self.DIRECTIONS)):
                if i == idx:
                    self._energy_history[i] = max(self._energy_history[i] * 0.7, energy)
                else:
                    self._energy_history[i] *= 0.7
            
            for i, dir_info in enumerate(self.DIRECTIONS):
                x = i * bar_width
                bar_height = int(self._energy_history[i] * (self.height - 25))
                
                if bar_height > 0:
                    if self._current_data.sound_type == SOUND_TYPE_FOOTSTEP:
                        color = COLORS['footstep']
                    elif self._current_data.sound_type == SOUND_TYPE_GUNSHOT:
                        color = COLORS['gunshot']
                    else:
                        color = COLORS['other']
                    
                    alpha = max(0.3, self._energy_history[i])
                    
                    self.create_rectangle(
                        x + gap, self.height - 15 - bar_height,
                        x + bar_width - gap, self.height - 15,
                        fill=color, outline='', tags='bar'
                    )
        else:
            for i in range(len(self.DIRECTIONS)):
                self._energy_history[i] *= 0.7
                bar_height = int(self._energy_history[i] * (self.height - 25))
                if bar_height > 0:
                    x = i * bar_width
                    self.create_rectangle(
                        x + gap, self.height - 15 - bar_height,
                        x + bar_width - gap, self.height - 15,
                        fill=COLORS['text_dim'], outline='', tags='bar'
                    )


class CompassWidget(tk.Canvas):
    """
    罗盘显示组件
    
    功能：
    - 画圆形罗盘
    - 显示方向标记（前/后/左/右）
    - 显示声音点（根据类型变色，根据距离变远近）
    """
    
    def __init__(self, parent, size=400, **kwargs):
        super().__init__(parent, width=size, height=size, 
                         bg=COLORS['bg'], highlightthickness=0, **kwargs)
        self.size = size
        self.center = size // 2
        self.radius = size // 2 - 20
        self._current_data = CompassData()
        self._draw_static()
    
    def _draw_static(self):
        """画静态元素（背景、刻度、文字）"""
        self.delete('all')
        
        c = self.center
        r = self.radius
        
        # 外圈
        self.create_oval(c - r, c - r, c + r, c + r,
                         outline=COLORS['compass_ring'], width=3)
        
        # 内圈（中距离）
        r_mid = int(r * 0.65)
        self.create_oval(c - r_mid, c - r_mid, c + r_mid, c + r_mid,
                         outline=COLORS['compass_grid'], width=1)
        
        # 内圈（近距离）
        r_near = int(r * 0.35)
        self.create_oval(c - r_near, c - r_near, c + r_near, c + r_near,
                         outline=COLORS['compass_grid'], width=1)
        
        # 十字线
        self.create_line(c, c - r, c, c + r, fill=COLORS['compass_grid'], width=1)
        self.create_line(c - r, c, c + r, c, fill=COLORS['compass_grid'], width=1)
        
        # 方向文字
        self.create_text(c, c - r - 12, text='前', fill=COLORS['text'], font=('Arial', 12, 'bold'))
        self.create_text(c, c + r + 12, text='后', fill=COLORS['text_dim'], font=('Arial', 10))
        self.create_text(c - r - 12, c, text='左', fill=COLORS['text_dim'], font=('Arial', 10))
        self.create_text(c + r + 12, c, text='右', fill=COLORS['text_dim'], font=('Arial', 10))
        
        # 中心点
        self.create_oval(c - 4, c - 4, c + 4, c + 4,
                         fill=COLORS['text_dim'], outline='')
    
    def update_data(self, data: CompassData):
        """更新显示数据"""
        self._current_data = data
        self._redraw()
    
    def _redraw(self):
        """重绘动态元素"""
        self._draw_static()
        
        data = self._current_data
        if not data.has_sound:
            return
        
        c = self.center
        r = self.radius
        
        # 计算点的位置
        # 角度 0=正上方(前)，顺时针
        rad = math.radians(90 - data.angle)
        
        # 距离映射：distance 0~1 → 半径 r*0.1 ~ r*0.9
        # 距离越大（越远），越靠外圈
        dist_factor = 0.1 + data.distance * 0.85  # 最近在 0.1R 处
        dist_factor = max(0.1, min(0.95, dist_factor))
        point_r = r * dist_factor
        
        x = c + point_r * math.cos(rad)
        y = c - point_r * math.sin(rad)
        
        # 颜色
        color = COLORS['other']
        if data.sound_type == SOUND_TYPE_FOOTSTEP:
            color = COLORS['footstep']
        elif data.sound_type == SOUND_TYPE_GUNSHOT:
            color = COLORS['gunshot']
        
        # 画点（大小根据能量）
        size = max(6, min(20, 8 + data.energy * 15))
        self.create_oval(x - size, y - size, x + size, y + size,
                         fill=color, outline='', tags='point')
        
        # 外圈光晕（枪声有爆炸效果）
        if data.sound_type == SOUND_TYPE_GUNSHOT:
            glow_size = size * 2
            self.create_oval(x - glow_size, y - glow_size, x + glow_size, y + glow_size,
                             outline=color, width=2, tags='glow')


class InfoPanel(tk.Frame):
    """信息面板：显示当前状态"""
    
    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=COLORS['bg'], **kwargs)
        
        self._build_ui()
    
    def _build_ui(self):
        # 状态行
        self.status_var = tk.StringVar(value='等待音频...')
        status_label = tk.Label(self, textvariable=self.status_var,
                                bg=COLORS['bg'], fg=COLORS['text_dim'],
                                font=('Consolas', 10))
        status_label.pack(anchor='w', pady=(0, 8))
        
        # 信息网格
        info_frame = tk.Frame(self, bg=COLORS['bg'])
        info_frame.pack(fill='x')
        
        # 方向
        tk.Label(info_frame, text='方向', bg=COLORS['bg'], fg=COLORS['text_dim'],
                 font=('Arial', 9)).grid(row=0, column=0, sticky='w', padx=(0, 20))
        self.angle_var = tk.StringVar(value='--')
        tk.Label(info_frame, textvariable=self.angle_var, bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Consolas', 14, 'bold')).grid(row=1, column=0, sticky='w', padx=(0, 20))
        
        # 响度
        tk.Label(info_frame, text='响度', bg=COLORS['bg'], fg=COLORS['text_dim'],
                 font=('Arial', 9)).grid(row=0, column=1, sticky='w', padx=20)
        self.distance_var = tk.StringVar(value='--')
        tk.Label(info_frame, textvariable=self.distance_var, bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Consolas', 14, 'bold')).grid(row=1, column=1, sticky='w', padx=20)
        
        # 类型
        tk.Label(info_frame, text='类型', bg=COLORS['bg'], fg=COLORS['text_dim'],
                 font=('Arial', 9)).grid(row=0, column=2, sticky='w', padx=20)
        self.type_var = tk.StringVar(value='--')
        self.type_label = tk.Label(info_frame, textvariable=self.type_var, bg=COLORS['bg'], 
                                    fg=COLORS['text'], font=('Consolas', 14, 'bold'))
        self.type_label.grid(row=1, column=2, sticky='w', padx=20)
        
        # 置信度
        tk.Label(info_frame, text='置信度', bg=COLORS['bg'], fg=COLORS['text_dim'],
                 font=('Arial', 9)).grid(row=0, column=3, sticky='w', padx=20)
        self.conf_var = tk.StringVar(value='--')
        tk.Label(info_frame, textvariable=self.conf_var, bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Consolas', 14, 'bold')).grid(row=1, column=3, sticky='w', padx=20)
    
    def update_data(self, data: CompassData):
        """更新显示"""
        if not data.has_sound:
            self.status_var.set('静音')
            self.angle_var.set('--')
            self.distance_var.set('--')
            self.type_var.set('--')
            self.conf_var.set('--')
            self.type_label.config(fg=COLORS['text_dim'])
            return
        
        self.status_var.set('检测到声音')
        self.angle_var.set(f'{data.angle:.1f}°')
        # 响度按能量分档：强/中/弱
        if data.energy > 0.6:
            vol_text = '强'
        elif data.energy > 0.3:
            vol_text = '中'
        else:
            vol_text = '弱'
        self.distance_var.set(vol_text)
        
        type_name = SOUND_TYPE_NAMES.get(data.sound_type, '其他')
        self.type_var.set(type_name)
        
        color = COLORS['text']
        if data.sound_type == SOUND_TYPE_FOOTSTEP:
            color = COLORS['footstep']
        elif data.sound_type == SOUND_TYPE_GUNSHOT:
            color = COLORS['gunshot']
        elif data.sound_type == SOUND_TYPE_OTHER:
            color = COLORS['other']
        self.type_label.config(fg=color)
        
        self.conf_var.set(f'{data.confidence*100:.0f}%')


class EchoCompassApp:
    """
    Echo Compass 主应用窗口
    
    用法:
        app = EchoCompassApp()
        app.set_data(compass_data)  # 更新数据
        app.run()
    """
    
    def __init__(self, title='Echo Compass 回声罗盘'):
        self.root = tk.Tk()
        self.root.title(title)
        self.root.configure(bg=COLORS['bg'])
        self.root.resizable(True, False)
        
        self._build_ui()
        
        self._data = CompassData()
    
    def _build_ui(self):
        # 顶部 8 方位显示条
        self.edge_display = EdgeDisplay(self.root, height=50)
        self.edge_display.pack(fill='x', padx=10, pady=(10, 5))
        
        # 标题
        title_frame = tk.Frame(self.root, bg=COLORS['bg'])
        title_frame.pack(fill='x', padx=20, pady=(0, 5))
        
        tk.Label(title_frame, text='回声罗盘', bg=COLORS['bg'], fg=COLORS['text'],
                 font=('Microsoft YaHei', 18, 'bold')).pack(side='left')
        tk.Label(title_frame, text='Echo Compass', bg=COLORS['bg'], fg=COLORS['text_dim'],
                 font=('Arial', 10)).pack(side='left', padx=(10, 0), pady=(8, 0))
        
        # 罗盘
        self.compass = CompassWidget(self.root, size=360)
        self.compass.pack(padx=20, pady=10)
        
        # 信息面板
        self.info = InfoPanel(self.root)
        self.info.pack(fill='x', padx=30, pady=(5, 15))
        
        # 底部状态栏（Label + 复制按钮）
        status_frame = tk.Frame(self.root, bg=COLORS['compass_bg'])
        status_frame.pack(fill='x', side='bottom')
        self.status_var = tk.StringVar(value='初始化中...')
        status_bar = tk.Label(status_frame, textvariable=self.status_var,
                              bg=COLORS['compass_bg'], fg=COLORS['text_dim'],
                              font=('Consolas', 9), anchor='w', padx=10, pady=4)
        status_bar.pack(side='left', fill='x', expand=True)
        copy_btn = tk.Button(status_frame, text='复制地址', command=self._copy_status_url,
                             bg=COLORS['compass_bg'], fg=COLORS['text_dim'],
                             activebackground=COLORS['compass_ring'],
                             activeforeground=COLORS['text'],
                             bd=0, font=('Consolas', 8), padx=8, pady=2)
        copy_btn.pack(side='right', padx=(0, 8))

    def _copy_status_url(self):
        """复制状态栏里的 web 地址到剪贴板，没有 URL 就复制整条状态"""
        text = self.status_var.get()
        url = text
        idx = text.find('http')
        if idx >= 0:
            # 截到第一个空白为止
            end = text.find(' ', idx)
            url = text[idx:] if end < 0 else text[idx:end]
        self.root.clipboard_clear()
        self.root.clipboard_append(url)

    def set_data(self, data: CompassData):
        """更新罗盘数据（线程安全）"""
        self._data = data
        # 用 after 调度到主线程更新 UI
        self.root.after(0, self._update_ui)

    def set_status(self, text: str):
        """设置状态栏文字"""
        self.status_var.set(text)
    
    def _update_ui(self):
        self.edge_display.update_data(self._data)
        self.compass.update_data(self._data)
        self.info.update_data(self._data)
    
    def run(self):
        """运行主循环"""
        self.root.mainloop()
    
    def stop(self):
        """停止"""
        self.root.quit()


if __name__ == '__main__':
    # 测试：模拟数据
    app = EchoCompassApp()
    
    import threading
    import time
    import random
    
    def simulate():
        angle = 0
        while True:
            angle = (angle + 3) % 360
            data = CompassData(
                has_sound=True,
                angle=angle,
                distance=0.3 + 0.4 * (1 + math.sin(math.radians(angle * 2))) / 2,
                sound_type=SOUND_TYPE_FOOTSTEP if angle < 180 else SOUND_TYPE_GUNSHOT,
                energy=0.7,
                confidence=0.85,
            )
            app.set_data(data)
            time.sleep(0.05)
    
    t = threading.Thread(target=simulate, daemon=True)
    t.start()
    
    app.set_status('演示模式：数据模拟中')
    app.run()
