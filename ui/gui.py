import tkinter as tk
from tkinter import ttk


def open_main_editor(mode):
    """Opens the main code editor window based on the selected mode."""
    welcome_root.destroy()

    root = tk.Tk()
    root.title("Code editor")
    root.geometry("900x900")
    main_paned = ttk.PanedWindow(root, orient=tk.HORIZONTAL)
    main_paned.pack(fill=tk.BOTH, expand=True)

    # 1. Left Sidebar Frame
    left_frame = ttk.Frame(main_paned, relief=tk.SUNKEN)

    # Mandatory lplus section
    label_lplus = ttk.Label(left_frame, text="Enter the file name", anchor=tk.W)
    label_lplus.pack(fill=tk.X, padx=5, pady=(5, 0))
    entry_lplus = ttk.Entry(left_frame)
    entry_lplus.pack(fill=tk.X, padx=5, pady=5)

    # Code Editor section ("enter code here")
    label_code = ttk.Label(left_frame, text="Enter code here", anchor=tk.W)
    label_code.pack(fill=tk.X, padx=5, pady=(5, 0))
    code_editor = tk.Text(left_frame, wrap=tk.NONE, bg="white")
    code_editor.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # If opened via "Add Question with Analyse", you can customize or show info
    if mode == "Add Question with Analyse":
        entry_lplus.insert(0, "analysis_mode_file")

    # 2. Right Paned Window (Vertical)
    right_paned = ttk.PanedWindow(main_paned, orient=tk.VERTICAL)

    # Top Right Frame (Output)
    top_right_frame = ttk.Frame(right_paned, relief=tk.SUNKEN)
    top_label = ttk.Label(top_right_frame, text="Output", anchor=tk.W)
    top_label.pack(fill=tk.X, padx=5, pady=(5, 0))
    output_text = tk.Text(top_right_frame, wrap=tk.NONE, bg="#f8f8f8")
    output_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # Bottom Right Frame (in_filename.txt input)
    bottom_right_frame = ttk.Frame(right_paned, relief=tk.SUNKEN)
    bottom_label = ttk.Label(bottom_right_frame, text="Test Cases", anchor=tk.W)
    bottom_label.pack(fill=tk.X, padx=5, pady=(5, 0))
    filename_input_text = tk.Text(bottom_right_frame, wrap=tk.NONE, bg="white")
    filename_input_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    # 3. Add frames to the vertical (right) paned window
    right_paned.add(top_right_frame, weight=1)
    right_paned.add(bottom_right_frame, weight=1)

    # 4. Add the left frame and the right paned window to the main horizontal paned window
    main_paned.add(left_frame, weight=1)
    main_paned.add(right_paned, weight=3)

    root.mainloop()


# --- Welcome Window Setup ---
welcome_root = tk.Tk()
welcome_root.title("DSA Management")
welcome_root.geometry("900x900")

welcome_main_paned = ttk.PanedWindow(welcome_root, orient=tk.HORIZONTAL)
welcome_main_paned.pack(fill=tk.BOTH, expand=True)

# 1. Left Sidebar Frame (Buttons)
welcome_left_frame = ttk.Frame(welcome_main_paned, relief=tk.SUNKEN)

label_options = ttk.Label(
    welcome_left_frame, text="Options", font=("Arial", 11, "bold"), anchor=tk.W
)
label_options.pack(fill=tk.X, padx=10, pady=(10, 5))

btn_new = ttk.Button(
    welcome_left_frame,
    text="New Question",
    command=lambda: open_main_editor("New Question"),
)
btn_new.pack(fill=tk.X, padx=10, pady=5, ipady=5)

btn_analyse = ttk.Button(
    welcome_left_frame,
    text="Add Question with Analyse",
    command=lambda: open_main_editor("Add Question with Analyse"),
)
btn_analyse.pack(fill=tk.X, padx=10, pady=5, ipady=5)

# 2. Right Paned Window (Vertical)
welcome_right_paned = ttk.PanedWindow(welcome_main_paned, orient=tk.VERTICAL)

# Top Right Frame (Status OK)
welcome_top_right = ttk.Frame(welcome_right_paned, relief=tk.SUNKEN)
status_label_title = ttk.Label(
    welcome_top_right, text="System Status", font=("Arial", 11, "bold"), anchor=tk.W
)
status_label_title.pack(fill=tk.X, padx=10, pady=(10, 5))

status_ok_label = ttk.Label(
    welcome_top_right,
    text="Status: OK",
    font=("Arial", 14),
    foreground="green",
    anchor=tk.W,
)
status_ok_label.pack(fill=tk.X, padx=10, pady=10)

# Bottom Right Frame (GitHub-style consistency heatmap)
welcome_bottom_right = ttk.Frame(welcome_right_paned, relief=tk.SUNKEN)
calendar_title = ttk.Label(
    welcome_bottom_right,
    text="Consistency Calendar",
    font=("Arial", 11, "bold"),
    anchor=tk.W,
)
calendar_title.pack(fill=tk.X, padx=10, pady=(10, 5))

# Canvas for GitHub green marking system grid simulation
cal_canvas = tk.Canvas(welcome_bottom_right, bg="white", highlightthickness=0)
cal_canvas.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)


def draw_github_calendar(event=None):
    cal_canvas.delete("all")
    # Simple color scale representing activity levels
    colors = ["#ebedf0", "#9be9a8", "#40c463", "#30a14e", "#216e39"]

    cols = 52  # weeks
    rows = 7  # days of the week
    cell_size = 12
    padding = 4

    import random

    random.seed(42)  # Consistent mock data generation

    for c in range(cols):
        for r in range(rows):
            x1 = c * (cell_size + padding) + 10
            y1 = r * (cell_size + padding) + 10
            x2 = x1 + cell_size
            y2 = y1 + cell_size

            # Random activity level for demo representation
            activity_level = random.choices(
                [0, 1, 2, 3, 4], weights=[40, 25, 15, 12, 8]
            )[0]
            color = colors[activity_level]

            cal_canvas.create_rectangle(
                x1, y1, x2, y2, fill=color, outline="#d1d5da", width=1
            )


cal_canvas.bind("<Configure>", draw_github_calendar)

# 3. Add frames to the vertical (right) paned window
welcome_right_paned.add(welcome_top_right, weight=1)
welcome_right_paned.add(welcome_bottom_right, weight=3)

# 4. Add the left frame and the right paned window to the main horizontal paned window
welcome_main_paned.add(welcome_left_frame, weight=1)
welcome_main_paned.add(welcome_right_paned, weight=3)

welcome_root.mainloop()

