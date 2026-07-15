"""
Echo Compass - 手机端 Web 雷达（第二块屏）
起一个本地 HTTP 服务，手机浏览器打开就是跟圆屏固件一致的罗盘页面。
数据推送用 SSE（Server-Sent Events），单向推送，零依赖（标准库）。

行为与 ESP32 固件保持一致：
  - 黑底、外圈圆、F/B/L/R 方位字母、中心点
  - 脚步/其他：蓝色圆点；枪声：红色带尖刺星形
  - 1.5s 以上无声后突然出声 → 整屏红闪三下
  - 500ms 无新数据 → 熄点

独立线程运行，起不来或没人连都不影响主程序。
"""

import json
import queue
import threading
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler


# ========== 罗盘网页（自包含 HTML） ==========
WEB_PAGE = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no">
<title>Echo Compass</title>
<style>
  html,body{margin:0;height:100%;background:#000;overflow:hidden;
    font-family:-apple-system,sans-serif;touch-action:none;}
  #wrap{position:fixed;inset:0;display:flex;align-items:center;justify-content:center;}
  canvas{display:block;}
  #btn{position:fixed;top:12px;right:12px;z-index:10;
    background:rgba(255,255,255,.12);color:#ddd;border:1px solid #555;
    border-radius:8px;padding:8px 12px;font-size:14px;cursor:pointer;}
  #btn:active{background:rgba(255,255,255,.25);}
  #stat{position:fixed;top:14px;left:12px;z-index:10;color:#666;font-size:12px;}
</style>
</head>
<body>
<div id="wrap"><canvas id="cv"></canvas></div>
<div id="stat">connecting...</div>
<button id="btn">全屏</button>
<script>
const cv=document.getElementById('cv'),ctx=cv.getContext('2d');
const stat=document.getElementById('stat'),btn=document.getElementById('btn');

// 与固件一致的比例
const R_RATIO=100/240, ICONR_RATIO=8/240, DOTR_RATIO=5/240;

// 状态
let hasSound=false, soundType=0, soundAngle=0, soundDistance=0.6;
let lastDataTime=0;

// 突发闪屏（匹配固件：1.5s 静默后出声闪三下，120ms 一相，红黑交替共 6 相）
let silenceStart=0;
let flashing=false, flashCount=0, flashStartTime=0;
const SILENCE_THRESH=1500, FLASH_DUR=120, FLASH_TOTAL=6;

function resize(){
  const s=Math.min(innerWidth,innerHeight);
  cv.width=s; cv.height=s;
}
addEventListener('resize',resize); resize();

// 角度+距离 → 坐标（0=正上，顺时针）
function angleToXY(a,d){
  const R=cv.width*R_RATIO;
  const rad=(a-90)*Math.PI/180;
  const r=R*(0.1+d*0.8);
  return [cv.width/2+r*Math.cos(rad), cv.height/2+r*Math.sin(rad)];
}

function drawBackground(){
  const w=cv.width, cx=w/2, cy=w/2, R=w*R_RATIO;
  ctx.fillStyle='#000'; ctx.fillRect(0,0,w,w);
  ctx.strokeStyle='#445'; ctx.lineWidth=Math.max(1,w/240);
  ctx.beginPath(); ctx.arc(cx,cy,R,0,2*Math.PI); ctx.stroke();
  ctx.strokeStyle='#222';
  ctx.beginPath(); ctx.arc(cx,cy,R-15*w/240,0,2*Math.PI); ctx.stroke();
  ctx.fillStyle='#555'; ctx.font=(10*w/240)+'px monospace';
  ctx.textAlign='center'; ctx.textBaseline='middle';
  ctx.fillText('F',cx,cy-R+14*w/240);
  ctx.fillText('B',cx,cy+R-14*w/240);
  ctx.fillText('L',cx-R+14*w/240,cy);
  ctx.fillText('R',cx+R-14*w/240,cy);
  ctx.fillStyle='#fff';
  ctx.beginPath(); ctx.arc(cx,cy,w*DOTR_RATIO,0,2*Math.PI); ctx.fill();
}

function drawStarBurst(cx,cy,r,color){
  const w=cv.width;
  const coreR=Math.max(2*w/240, r/2);
  ctx.fillStyle=color;
  ctx.beginPath(); ctx.arc(cx,cy,coreR,0,2*Math.PI); ctx.fill();
  const n=7, len=r, sw=Math.max(1.5,w/240*2);
  ctx.strokeStyle=color; ctx.lineWidth=sw;
  for(let i=0;i<n;i++){
    const a=i*2*Math.PI/n;
    const x1=cx+coreR*Math.cos(a), y1=cy+coreR*Math.sin(a);
    const x2=cx+len*Math.cos(a), y2=cy+len*Math.sin(a);
    ctx.beginPath(); ctx.moveTo(x1,y1); ctx.lineTo(x2,y2); ctx.stroke();
    const ox=sw*Math.cos(a+Math.PI/2), oy=sw*Math.sin(a+Math.PI/2);
    ctx.beginPath(); ctx.moveTo(x1+ox,y1+oy); ctx.lineTo(x2+ox,y2+oy); ctx.stroke();
  }
}

function drawIcon(){
  const w=cv.width;
  let [x,y]=angleToXY(soundAngle,soundDistance);
  const cx=w/2, cy=w/2, R=w*R_RATIO, iconR=w*ICONR_RATIO;
  // 限制在罗盘内
  const dx=x-cx, dy=y-cy, dist=Math.hypot(dx,dy);
  if(dist>R-iconR){ const sc=(R-iconR)/dist; x=cx+dx*sc; y=cy+dy*sc; }
  let color;
  if(soundType===2) color='#f00';        // 枪声红
  else if(soundType===1) color='#19f';   // 脚步蓝
  else color='#fff';                      // 其他白
  if(soundType===2) drawStarBurst(x,y,iconR,color);
  else { ctx.fillStyle=color; ctx.beginPath(); ctx.arc(x,y,iconR,0,2*Math.PI); ctx.fill(); }
}

function drawFullRed(){
  const w=cv.width, cx=w/2, cy=w/2, R=w*R_RATIO;
  ctx.fillStyle='#f00'; ctx.fillRect(0,0,w,w);
  ctx.strokeStyle='#222'; ctx.beginPath(); ctx.arc(cx,cy,R,0,2*Math.PI); ctx.stroke();
  ctx.fillStyle='#000';
  ctx.font=(10*w/240)+'px monospace'; ctx.textAlign='center'; ctx.textBaseline='middle';
  ctx.fillText('F',cx,cy-R+14*w/240); ctx.fillText('B',cx,cy+R-14*w/240);
  ctx.fillText('L',cx-R+14*w/240,cy); ctx.fillText('R',cx+R-14*w/240,cy);
  ctx.beginPath(); ctx.arc(cx,cy,w*DOTR_RATIO,0,2*Math.PI); ctx.fill();
}

function render(){
  const now=Date.now();
  // 安全超时：500ms 无新数据 → 熄点
  if(lastDataTime && now-lastDataTime>500){ hasSound=false; }
  if(flashing){
    if(now-flashStartTime>=FLASH_DUR){
      flashCount++;
      if(flashCount>=FLASH_TOTAL){ flashing=false; }
      else { flashStartTime=now; }
    }
    if(flashing){
      if(flashCount%2===0) drawFullRed();
      else { drawBackground(); if(hasSound) drawIcon(); }
    } else {
      drawBackground(); if(hasSound) drawIcon();
    }
  } else {
    drawBackground();
    if(hasSound) drawIcon();
  }
  requestAnimationFrame(render);
}
render();

// 接收数据
const es=new EventSource('/stream');
es.onopen=()=>{ stat.textContent='connected'; };
es.onerror=()=>{ stat.textContent='reconnecting...'; };
es.onmessage=(e)=>{
  const d=JSON.parse(e.data);
  const now=Date.now();
  lastDataTime=now;
  const prevHas=hasSound;
  hasSound=!!d.has_sound;
  soundType=d.sound_type||0;
  soundAngle=d.angle||0;
  soundDistance=d.distance!=null?d.distance:0.6;
  // 突发闪屏检测（匹配固件）
  if(!prevHas && hasSound){
    if(silenceStart>0 && now-silenceStart>=SILENCE_THRESH){
      flashing=true; flashCount=0; flashStartTime=now;
    }
  }
  if(hasSound) silenceStart=0;
  else { if(silenceStart===0) silenceStart=now; }
};

// 全屏 + 屏幕常亮
let wakeLock=null;
btn.onclick=async()=>{
  try{
    if(!document.fullscreenElement) await document.documentElement.requestFullscreen();
    if('wakeLock' in navigator){ wakeLock=await navigator.wakeLock.request('screen'); }
    btn.textContent='已全屏';
  }catch(err){ stat.textContent='全屏失败: '+err.message; }
};
addEventListener('fullscreenchange',()=>{
  btn.textContent=document.fullscreenElement?'退出':'全屏';
});
// 可见性变化时重新申请常亮
addEventListener('visibilitychange',async()=>{
  if(wakeLock!==null && document.visibilityState==='visible'){
    try{ wakeLock=await navigator.wakeLock.request('screen'); }catch(e){}
  }
});
</script>
</body>
</html>
"""


class WebRadarServer:
    """手机端 Web 雷达服务。独立线程，失败不影响主程序。"""

    def __init__(self, port=8090):
        self.port = port
        self._clients = {}          # client_id -> queue.Queue
        self._lock = threading.Lock()
        self._next_id = 0
        self._server = None
        self._thread = None
        self._running = False

    def start(self):
        """启动服务。成功返回 True，失败返回 False（不抛异常，不影响主程序）。"""
        try:
            server = self  # 闭包捕获

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args):
                    pass  # 静默，不刷屏

                def do_GET(self):
                    if self.path in ('/', '/index.html') or self.path.startswith('/?'):
                        body = WEB_PAGE.encode('utf-8')
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/html; charset=utf-8')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        try:
                            self.wfile.write(body)
                        except Exception:
                            pass
                    elif self.path == '/stream':
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Cache-Control', 'no-cache')
                        self.send_header('Connection', 'keep-alive')
                        self.end_headers()
                        # 注册客户端：每个连接一个队列，由本线程独占写 socket，避免并发写
                        cid = server._next_id
                        server._next_id += 1
                        q = queue.Queue()
                        with server._lock:
                            server._clients[cid] = q
                        try:
                            last_keepalive = time.time()
                            while server._running:
                                try:
                                    b = q.get(timeout=1.0)
                                    self.wfile.write(b)
                                    self.wfile.flush()
                                except queue.Empty:
                                    # 每 5 秒发个注释保活，顺便探测死连接
                                    if time.time() - last_keepalive > 5:
                                        self.wfile.write(b': ping\n\n')
                                        self.wfile.flush()
                                        last_keepalive = time.time()
                                except Exception:
                                    break
                        finally:
                            with server._lock:
                                server._clients.pop(cid, None)
                    else:
                        self.send_response(404)
                        self.end_headers()

            self._server = ThreadingHTTPServer(('0.0.0.0', self.port), Handler)
            self._running = True
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
            return True
        except Exception:
            self._running = False
            return False

    def push(self, data_dict):
        """把罗盘数据广播给所有连接的手机。data_dict 是可 JSON 序列化的字典。"""
        if not self._running:
            return
        try:
            msg = 'data: ' + json.dumps(data_dict, ensure_ascii=False) + '\n\n'
            b = msg.encode('utf-8')
            with self._lock:
                qs = list(self._clients.values())
            for q in qs:
                try:
                    q.put_nowait(b)
                except Exception:
                    pass
        except Exception:
            pass

    def stop(self):
        self._running = False
        if self._server:
            try:
                self._server.shutdown()
            except Exception:
                pass


def get_local_ip():
    """取本机局域网 IP，用于提示手机访问地址。"""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'
