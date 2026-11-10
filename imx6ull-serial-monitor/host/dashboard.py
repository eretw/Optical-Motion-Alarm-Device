"""Small desktop dashboard; Tk widgets are only accessed on the main thread."""
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from client import Client
from transport import SimTransport, open_serial, serial_ports
from protocol import HELLO, CONFIG, SILENCE, STOP

class Dashboard:
    def __init__(self, root):
        self.root, self.client, self.busy = root, None, False
        self.actions = queue.Queue()
        root.title("i.MX6ULL USB 串口监测终端")
        root.geometry("900x620")
        self.port = tk.StringVar(value="模拟模式")
        self.state = tk.StringVar(value="先选择模拟模式，或刷新并选择 CH340 串口")
        self.sample = tk.StringVar(value="等待数据")
        self.cfg = [tk.StringVar(value=x) for x in ("200", "3000", "4000")]
        frame = ttk.Frame(root, padding=16); frame.pack(fill="both", expand=True)
        top = ttk.Frame(frame); top.pack(fill="x")
        self.combo = ttk.Combobox(top, textvariable=self.port, width=32, state="readonly")
        self.combo.pack(side="left")
        ttk.Button(top, text="刷新串口", command=self.refresh).pack(side="left", padx=5)
        ttk.Button(top, text="连接", command=self.connect).pack(side="left")
        ttk.Button(top, text="断开", command=self.disconnect).pack(side="left", padx=5)
        ttk.Label(frame, textvariable=self.state, wraplength=840).pack(anchor="w", pady=12)
        ttk.Label(frame, textvariable=self.sample, font=("Consolas", 14), justify="left").pack(anchor="w", pady=8)
        cfg = ttk.Frame(frame); cfg.pack(fill="x", pady=12)
        for label, var in zip(("采样周期 ms", "光照原始阈值", "运动原始阈值"), self.cfg):
            ttk.Label(cfg, text=label).pack(side="left")
            ttk.Entry(cfg, textvariable=var, width=8).pack(side="left", padx=5)
        ttk.Button(cfg, text="保存到板端", command=self.configure).pack(side="left", padx=5)
        buttons = ttk.Frame(frame); buttons.pack(fill="x")
        ttk.Button(buttons, text="消音", command=lambda:self.command(SILENCE)).pack(side="left")
        ttk.Button(buttons, text="退出板端程序 / 恢复终端", command=lambda:self.command(STOP)).pack(side="left", padx=8)
        self.log = tk.Text(frame, height=16, wrap="word", state="disabled")
        self.log.pack(fill="both", expand=True, pady=12)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh(); root.after(100, self.poll)

    def refresh(self):
        try:
            self.combo["values"] = ["模拟模式"] + [f"{p} | {n}" for p,n,_ in serial_ports()]
        except Exception as exc:
            self.combo["values"] = ["模拟模式"]
            self.state.set(str(exc))

    def launch(self, fn):
        if self.busy:
            return
        self.busy = True
        def work():
            try:
                self.actions.put(("result", fn()))
            except Exception as exc:
                self.actions.put(("error", str(exc)))
            finally:
                self.actions.put(("idle", None))
        threading.Thread(target=work, daemon=True).start()

    def connect(self):
        if self.client or self.busy:
            return
        selected = self.port.get()
        def work():
            c = Client(SimTransport() if selected=="模拟模式" else open_serial(selected.split(" | ")[0]),
                       Path(__file__).resolve().parents[1]/"logs")
            try:
                result = c.request(HELLO)
            except Exception:
                c.close(); raise
            self.actions.put(("connected", c))
            return result
        self.launch(work)

    def disconnect(self):
        if self.busy:
            return
        c = self.client; self.client = None
        if c:
            self.launch(lambda:c.close())
        self.state.set("已断开；板端会继续采集并缓存告警")

    def configure(self):
        values = ",".join(v.get().strip() for v in self.cfg)
        self.command(CONFIG, values)

    def command(self, kind, payload=b""):
        if not self.client:
            messagebox.showinfo("提示", "请先连接")
            return
        c = self.client
        self.launch(lambda:c.request(kind, payload))

    def add_log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text+"\n")
        if int(self.log.index("end-1c").split(".")[0])>300:
            self.log.delete("1.0", "101.0")
        self.log.see("end");self.log.configure(state="disabled")

    def poll(self):
        while not self.actions.empty():
            kind, value = self.actions.get_nowait()
            if kind=="connected": self.client=value;self.state.set("已连接")
            elif kind=="idle": self.busy=False
            else: self.add_log(f"{kind}: {value}");self.state.set(str(value))
        c = self.client
        if c:
            for _ in range(200):
                try: kind,value=c.notifications.get_nowait()
                except queue.Empty: break
                if kind=="sample":
                    self.sample.set(f"光照(raw): {value.get('als')}   运动(raw): {value.get('motion')}\n"
                        f"加速度(raw): {value.get('ax')}, {value.get('ay')}, {value.get('az')}\n"
                        f"报警: {value.get('alarm')}   数据有效: {value.get('valid')}   丢弃事件: {value.get('dropped')}")
                else: self.add_log(f"{kind}: {value}")
                if kind=="disconnected": self.state.set("连接已中断；断开后可重新连接")
        self.root.after(100,self.poll)

    def close(self):
        if self.client:self.client.close()
        self.root.destroy()

if __name__=="__main__":
    root=tk.Tk();Dashboard(root);root.mainloop()
