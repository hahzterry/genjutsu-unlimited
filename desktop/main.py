"""Tkinter desktop mirror of the Genjutsu Unlimited UI.

Talks to the FastAPI backend (BACKEND_URL env or http://localhost:8000).
Run:  python main.py
"""
import os
import threading
import requests
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
DEFAULT_PROMPT = ("A cyberpunk samurai walking through neon Tokyo streets "
                  "at night, dramatic lighting, cinematic")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Genjutsu Unlimited")
        self.geometry("900x700")
        self.configure(bg="#0a0a0a")
        self.file_path = None
        self.video_url = None
        self._build()

    def _build(self):
        tk.Label(self, text="Genjutsu Unlimited", bg="#0a0a0a", fg="#bb00ff",
                 font=("Helvetica", 20, "bold")).pack(pady=10)

        self.upload_btn = tk.Button(self, text="DROP REFERENCE VIDEO OR IMAGE HERE\n"
                                               "Genjutsu will transfer motion/style to new scene",
                                    bg="#121014", fg="#f5f5f7", activebackground="#1a0a22",
                                    relief="solid", bd=1, height=6, font=("Helvetica", 11),
                                    command=self.pick_file)
        self.upload_btn.pack(fill="x", padx=20, pady=10)

        tk.Label(self, text="PROMPT", bg="#0a0a0a", fg="#888",
                 font=("Helvetica", 8, "bold")).pack(anchor="w", padx=24)
        self.prompt = tk.Text(self, height=3, bg="#121014", fg="#f5f5f7",
                             insertbackground="#fff", relief="flat", font=("Helvetica", 11))
        self.prompt.insert("1.0", DEFAULT_PROMPT)
        self.prompt.pack(fill="x", padx=20, pady=4)

        self.gen_btn = tk.Button(self, text="GENERATE WITH GENJUTSU", bg="#bb00ff",
                                 fg="white", activebackground="#7a00b3",
                                 relief="flat", height=2, font=("Helvetica", 13, "bold"),
                                 command=self.generate)
        self.gen_btn.pack(fill="x", padx=20, pady=12)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=20, pady=4)

        self.logs = scrolledtext.ScrolledText(self, height=10, bg="#121014", fg="#9cd",
                                              insertbackground="#fff", relief="flat",
                                              font=("Courier", 10))
        self.logs.pack(fill="both", expand=True, padx=20, pady=10)

        self.dl_btn = tk.Button(self, text="Download result", bg="#121014", fg="#bb00ff",
                                relief="solid", bd=1, state="disabled",
                                command=self.download)
        self.dl_btn.pack(pady=8)

    def log(self, msg):
        self.logs.insert("end", msg + "\n")
        self.logs.see("end")

    def pick_file(self):
        p = filedialog.askopenfilename(filetypes=[("Media", "*.mp4 *.mov *.png *.jpg *.jpeg")])
        if p:
            self.file_path = p
            self.upload_btn.config(text=f"loaded: {os.path.basename(p)}")

    def generate(self):
        if not self.file_path:
            self.log("pick a reference file first")
            return
        self.gen_btn.config(state="disabled")
        self.progress["value"] = 0
        self.logs.delete("1.0", "end")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            with open(self.file_path, "rb") as f:
                r = requests.post(f"{BACKEND}/generate",
                                  files={"file": f},
                                  data={"prompt": self.prompt.get("1.0", "end").strip()})
            r.raise_for_status()
            jid = r.json()["jobId"]
            self.log(f"job {jid} queued")

            import time
            while True:
                time.sleep(3)
                v = requests.get(f"{BACKEND}/jobs/{jid}/video", stream=True, allow_redirects=False)
                if v.status_code == 200:
                    self.video_url = f"{BACKEND}/jobs/{jid}/video"
                    self.progress["value"] = 100
                    self.log("done — ready to download")
                    self.dl_btn.config(state="normal")
                    break
                self.progress["value"] = min(95, self.progress["value"] + 5)
        except Exception as e:
            self.log(f"error: {e}")
        finally:
            self.gen_btn.config(state="normal")

    def download(self):
        if not self.video_url:
            return
        dst = filedialog.asksaveasfilename(defaultextension=".mp4",
                                           filetypes=[("Video", "*.mp4")])
        if not dst:
            return
        r = requests.get(self.video_url, stream=True)
        with open(dst, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        self.log(f"saved -> {dst}")


if __name__ == "__main__":
    App().mainloop()
