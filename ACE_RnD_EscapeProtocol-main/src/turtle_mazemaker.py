import turtle
import tkinter as tk
from tkinter import filedialog
import json
import os
import math

# --- Tkinter Setup ---
root = tk.Tk()
root.title("Maze Editor 2.0")

frame_left = tk.Frame(root)
frame_left.pack(side="left", padx=10, pady=10)

frame_right = tk.Frame(root)
frame_right.pack(side="right", padx=10, pady=10)

canvas = turtle.ScrolledCanvas(frame_right, width=600, height=600)
canvas.pack()
screen = turtle.TurtleScreen(canvas)
screen.tracer(0)

drawer = turtle.RawTurtle(screen)
drawer.hideturtle()
drawer.speed(0)

preview_turtle = turtle.RawTurtle(screen)
preview_turtle.hideturtle()
preview_turtle.pensize(2)
preview_turtle.color("gray")

walls = []
clicks = []
start_pos = (-180, 180)
goal_pos = (180, -180)
line_mode = tk.StringVar(value="straight")
delete_mode = tk.BooleanVar(value=False)
set_mode = tk.StringVar(value="draw")  # 'draw', 'start', 'goal', 'delete'

# --- Start & Goal markers ---
start_marker = turtle.RawTurtle(screen)
start_marker.hideturtle()
start_marker.penup()
start_marker.goto(start_pos)
start_marker.color("blue")
start_marker.dot(20)

goal_marker = turtle.RawTurtle(screen)
goal_marker.hideturtle()
goal_marker.penup()
goal_marker.goto(goal_pos)
goal_marker.color("green")
goal_marker.dot(20)

# --- UI Elements ---
maze_name_label = tk.Label(frame_left, text="Maze Name:")
maze_name_label.pack()

maze_name_entry = tk.Entry(frame_left)
maze_name_entry.pack(pady=5)
maze_name_entry.insert(0, "maze1")

line_toggle = tk.Checkbutton(
    frame_left,
    text="Allow Slanting Lines",
    variable=line_mode,
    onvalue="slant",
    offvalue="straight",
)
line_toggle.pack(pady=5)

# --- Mode Buttons ---
def set_draw_mode():
    set_mode.set("draw")
    status_label.config(text="🖊 Drawing mode")

def set_delete_mode():
    set_mode.set("delete")
    status_label.config(text="🗑 Click near a wall to delete it")

def set_start_mode():
    set_mode.set("start")
    status_label.config(text="🔵 Click to set START position")

def set_goal_mode():
    set_mode.set("goal")
    status_label.config(text="🟢 Click to set GOAL position")

mode_label = tk.Label(frame_left, text="Editor Modes:")
mode_label.pack(pady=(10, 0))

btn_draw = tk.Button(frame_left, text="✏️ Draw Walls", command=set_draw_mode)
btn_draw.pack(pady=2)

btn_delete = tk.Button(frame_left, text="🗑 Delete Walls", command=set_delete_mode)
btn_delete.pack(pady=2)

btn_start = tk.Button(frame_left, text="🔵 Set Start", command=set_start_mode)
btn_start.pack(pady=2)

btn_goal = tk.Button(frame_left, text="🟢 Set Goal", command=set_goal_mode)
btn_goal.pack(pady=2)

status_label = tk.Label(frame_left, text="Click to draw walls (2 clicks per wall)")
status_label.pack(pady=10)

# --- Drawing Functions ---
def preview_wall(x, y):
    preview_turtle.clear()
    if len(clicks) != 1:
        return

    x1, y1 = clicks[0]
    x2, y2 = x, y

    if line_mode.get() == "straight":
        dx = abs(x2 - x1)
        dy = abs(y2 - y1)
        if dx > dy:
            y2 = y1
        else:
            x2 = x1

    preview_turtle.penup()
    preview_turtle.goto(x1, y1)
    preview_turtle.pendown()
    preview_turtle.goto(x2, y2)

def onclick(x, y):
    """Handle clicks for drawing, deleting, or setting start/goal."""
    global clicks, start_pos, goal_pos

    # --- Set Start / Goal Mode ---
    if set_mode.get() == "start":
        start_pos = (int(x), int(y))
        start_marker.clear()
        start_marker.goto(start_pos)
        start_marker.dot(20)
        screen.update()
        status_label.config(text=f"🔵 Start position set to {start_pos}")
        return

    if set_mode.get() == "goal":
        goal_pos = (int(x), int(y))
        goal_marker.clear()
        goal_marker.goto(goal_pos)
        goal_marker.dot(20)
        screen.update()
        status_label.config(text=f"🟢 Goal position set to {goal_pos}")
        return

    # --- Delete Mode ---
    if set_mode.get() == "delete":
        delete_nearest_wall(x, y)
        return

    # --- Drawing Mode ---
    clicks.append((x, y))
    if len(clicks) == 2:
        x1, y1 = clicks[0]
        x2, y2 = clicks[1]

        if line_mode.get() == "straight":
            dx = abs(x2 - x1)
            dy = abs(y2 - y1)
            if dx > dy:
                y2 = y1
            else:
                x2 = x1

        drawer.penup()
        drawer.goto(x1, y1)
        drawer.pendown()
        drawer.goto(x2, y2)
        walls.append([int(x1), int(y1), int(x2), int(y2)])

        clicks.clear()
        preview_turtle.clear()
        screen.update()

screen.onclick(onclick)

def motion_handler(event):
    """Track mouse motion for live preview."""
    if len(clicks) == 1 and set_mode.get() == "draw":
        width = canvas.winfo_width()
        height = canvas.winfo_height()
        x = event.x - width / 2
        y = height / 2 - event.y
        preview_wall(x, y)
        root.after_idle(lambda: screen.update())

screen.cv.bind("<Motion>", motion_handler)

# --- Utility: Distance from point to line ---
def point_to_line_dist(px, py, x1, y1, x2, y2):
    line_len_sq = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if line_len_sq == 0:
        return math.hypot(px - x1, py - y1)
    t = max(0, min(1, ((px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)) / line_len_sq))
    proj_x = x1 + t * (x2 - x1)
    proj_y = y1 + t * (y2 - y1)
    return math.hypot(px - proj_x, py - proj_y)

# --- Delete Wall ---
def delete_nearest_wall(x, y):
    if not walls:
        status_label.config(text="⚠️ No walls to delete.")
        return

    threshold = 10
    nearest_index = None
    nearest_dist = float("inf")

    for i, (x1, y1, x2, y2) in enumerate(walls):
        dist = point_to_line_dist(x, y, x1, y1, x2, y2)
        if dist < nearest_dist:
            nearest_dist = dist
            nearest_index = i

    if nearest_dist <= threshold and nearest_index is not None:
        deleted_wall = walls.pop(nearest_index)
        redraw_all_walls()
        status_label.config(text=f"🗑 Deleted wall: {deleted_wall}")
    else:
        status_label.config(text="⚠️ Click closer to a wall to delete it.")

def redraw_all_walls():
    drawer.clear()
    preview_turtle.clear()
    for x1, y1, x2, y2 in walls:
        drawer.penup()
        drawer.goto(x1, y1)
        drawer.pendown()
        drawer.goto(x2, y2)
    screen.update()

# --- Undo ---
def undo_last_wall():
    if walls:
        walls.pop()
        redraw_all_walls()
        status_label.config(text="↩️ Last wall removed.")
    else:
        status_label.config(text="⚠️ No walls to undo.")

undo_button = tk.Button(frame_left, text="Undo Last Wall", command=undo_last_wall)
undo_button.pack(pady=5)

# --- Save Maze ---
def save_maze():
    name = maze_name_entry.get().strip()
    if not name:
        status_label.config(text="⚠️ Please enter a maze name before saving.")
        return

    maze_data = {
        "name": name,
        "walls": walls,
        "start": start_pos,
        "goal": goal_pos,
    }

    dir_name = "src/mazes"
    filename = os.path.join(dir_name, f"{name}.json")
    try:
        os.makedirs(dir_name, exist_ok=True)
        with open(filename, "w") as f:
            json.dump(maze_data, f, indent=2)
        status_label.config(text=f"✅ Maze saved to {filename}")
    except Exception as e:
        status_label.config(text=f"❌ Error saving maze: {e}")

save_button = tk.Button(frame_left, text="Save Maze", command=save_maze)
save_button.pack(pady=10)

# --- Load Maze ---
def load_maze():
    global walls, start_pos, goal_pos
    file_path = filedialog.askopenfilename(
        title="Select a Maze JSON File",
        filetypes=[("JSON Files", "*.json")],
        initialdir="src/mazes"
    )
    if not file_path:
        return

    try:
        with open(file_path, "r") as f:
            data = json.load(f)

        walls.clear()
        drawer.clear()
        preview_turtle.clear()

        for x1, y1, x2, y2 in data.get("walls", []):
            drawer.penup()
            drawer.goto(x1, y1)
            drawer.pendown()
            drawer.goto(x2, y2)
            walls.append([x1, y1, x2, y2])

        start_pos = tuple(data.get("start", start_pos))
        goal_pos = tuple(data.get("goal", goal_pos))
        start_marker.clear()
        goal_marker.clear()
        start_marker.goto(start_pos)
        start_marker.dot(20)
        goal_marker.goto(goal_pos)
        goal_marker.dot(20)

        maze_name_entry.delete(0, tk.END)
        maze_name_entry.insert(0, data.get("name", "Unnamed"))

        screen.update()
        status_label.config(text=f"📂 Loaded maze: {os.path.basename(file_path)}")

    except Exception as e:
        status_label.config(text=f"❌ Error loading maze: {e}")

load_button = tk.Button(frame_left, text="Load Maze", command=load_maze)
load_button.pack(pady=5)

screen.update()
root.mainloop()