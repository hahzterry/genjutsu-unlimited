"""Tkinter desktop mirror of the Genjutsu Unlimited UI (v3.0 — dual upload).

Talks to the FastAPI backend (BACKEND_URL env or http://localhost:8000).
Supports: reference video (required, 4-30s) + up to 30 reference images.
Run:  python main.py
"""
import os
import threading
import requests
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
API_KEY = os.getenv("API_KEY", "")
DEFAULT_PROMPT = ("A cyberpunk samurai walking through neon Tokyo streets "
                  "at night, dramatic lighting, cinematic")


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Genjutsu Unlimited")
        self.geometry("900x750")
        self.configure(bg="#0a0a0a")
        self.video_path = None
        self.image_paths: list[str] = []
        self.video_url = None
        self._build()

    def _build(self):
        tk.Label(self, text="Genjutsu Unlimited", bg="#0a0a0a", fg="#c4f542",
                 font=("Helvetica", 20, "bold")).pack(pady=10)

        # Reference video (required)
        tk.Label(self, text="REFERENCE VIDEO (4–30 seconds) *", bg="#0a0a0a", fg="#888",
                 font=("Helvetica", 8, "bold")).pack(anchor="w", padx=24)
        self.video_btn = tk.Button(self, text="Add a reference video to extract motion\nVideo duration: 4–30 seconds",
                                   bg="#121014", fg="#f5f5f7", activebackground="#1a0a22",
                                   relief="solid", bd=1, height=4, font=("Helvetica", 10),
                                   command=self.pick_video)
        self.video_btn.pack(fill="x", padx=20, pady=4)

        # Reference images (optional, up to 30)
        tk.Label(self, text="REFERENCE IMAGES (up to 30)", bg="#0a0a0a", fg="#888",
                 font=("Helvetica", 8, "bold")).pack(anchor="w", padx=24)
        self.img_btn = tk.Button(self, text="Add your characters, products, or clothes\nUp to 30 images",
                                  bg="#121014", fg="#f5f5f7", activebackground="#1a0a22",
                                  relief="solid", bd=1, height=3, font=("Helvetica", 10),
                                  command=self.pick_images)
        self.img_btn.pack(fill="x", padx=20, pady=4)

        self.img_count = tk.Label(self, text="0/30 images added", bg="#0a0a0a", fg="#666",
                                   font=("Helvetica", 9))
        self.img_count.pack(anchor="w", padx=24)

        # Mode
        self.mode_var = tk.StringVar(value="motion_transfer")
        mode_frame = tk.Frame(self, bg="#0a0a0a")
        mode_frame.pack(fill="x", padx=20, pady=4)
        tk.Radiobutton(mode_frame, text="Motion transfer", variable=self.mode_var,
                       value="motion_transfer", bg="#0a0a0a", fg="#f5f5f7",
                       selectcolor="#121014", font=("Helvetica", 10)).pack(side="left")
        tk.Radiobutton(mode_frame, text="Objects swap", variable=self.mode_var,
                       value="objects_swap", bg="#0a0a0a", fg="#f5f5f7",
                       selectcolor="#121014", font=("Helvetica", 10)).pack(side="left")

        # Prompt
        tk.Label(self, text="PROMPT", bg="#0a0a0a", fg="#888",
                 font=("Helvetica", 8, "bold")).pack(anchor="w", padx=24)
        self.prompt = tk.Text(self, height=3, bg="#121014", fg="#f5f5f7",
                             insertbackground="#fff", relief="flat", font=("Helvetica", 11))
        self.prompt.insert("1.0", DEFAULT_PROMPT)
        self.prompt.pack(fill="x", padx=20, pady=4)

        # Generate
        self.gen_btn = tk.Button(self, text="Generate", bg="#c4f542",
                                 fg="black", activebackground="#a3d136",
                                 relief="flat", height=2, font=("Helvetica", 13, "bold"),
                                 command=self.generate)
        self.gen_btn.pack(fill="x", padx=20, pady=12)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=20, pady=4)

        self.logs = scrolledtext.ScrolledText(self, height=10, bg="#121014", fg="#9cd",
                                              insertbackground="#fff", relief="flat",
                                              font=("Courier", 10))
        self.logs.pack(fill="both", expand=True, padx=20, pady=10)

        self.dl_btn = tk.Button(self, text="Download result", bg="#121014", fg="#c4f542",
                                relief="solid", bd=1, state="disabled",
                                command=self.download)
        self.dl_btn.pack(pady=8)

    def log(self, msg):
        self.logs.insert("end", msg + "\n")
        self.logs.see("end")

    def pick_video(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.webm *.avi")])
        if p:
            self.video_path = p
            self.video_btn.config(text=f"Video: {os.path.basename(p)}")

    def pick_images(self):
        paths = filedialog.askopenfilenames(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.gif")])
        if paths:
            self.image_paths = list(paths)[:30]
            self.img_count.config(text=f"{len(self.image_paths)}/30 images added")

    def generate(self):
        if not self.video_path:
            self.log("pick a reference video first (4–30 seconds)")
            return
        self.gen_btn.config(state="disabled")
        self.progress["value"] = 0
        self.logs.delete("1.0", "end")
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        try:
            files = [("video", (os.path.basename(self.video_path), open(self.video_path, "rb"), "video/mp4"))]
            for ip in self.image_paths:
                files.append(("images", (os.path.basename(ip), open(ip, "rb"), "image/jpeg")))
            data = {
                "prompt": self.prompt.get("1.0", "end").strip(),
                "mode": self.mode_var.get(),
            }
            headers = {}
            if API_KEY:
                headers["X-API-Key"] = API_KEY

            r = requests.post(f"{BACKEND}/generate", files=files, data=data, headers=headers)
            r.raise_for_status()
            jid = r.json()["jobId"]
            self.log(f"job {jid} queued")

            import time
            while True:
                time.sleep(3)
                v = requests.get(f"{BACKEND}/jobs/{jid}/video", stream=True, allow_redirects=False, headers=headers)
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
        headers = {}
        if API_KEY:
            headers["X-API-Key"] = API_KEY
        r = requests.get(self.video_url, stream=True, headers=headers)
        with open(dst, "wb") as f:
            for chunk in r.iter_content(8192):
                f.write(chunk)
        self.log(f"saved -> {dst}")


if __name__ == "__main__":
    App().mainloop()
