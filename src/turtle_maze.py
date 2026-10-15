import turtle
import tkinter as tk
import time
import json
import math
import tkinter.messagebox as msg
import tkinter.simpledialog as simpledialog

PLAYER_USERNAME = ""
# ------------------ CONFIG ------------------
maze_files = [
    r"ACE_RnD_EscapeProtocol-main/src/mazes/Polygon.json",
]
current_maze_index = 0
scores = {}
timer_running = False
start_time = 0

# --------------------------------------------

# --- Main Tkinter window ---
root = tk.Tk()
root.title("Escape Protocol")

# Layout: left side controls, right side turtle canvas
frame_left = tk.Frame(root)
frame_left.pack(side="left", padx=10, pady=10)

frame_right = tk.Frame(root)
frame_right.pack(side="right", padx=10, pady=10)

# --- Turtle Canvas inside Tkinter ---
border_frame = tk.Frame(frame_right, bd=0, relief="flat", highlightthickness=5, highlightbackground="white")
border_frame.pack(padx=0, pady=0)

maze_label = tk.Label(
    border_frame,
    text="",
    font=("Arial", 16, "bold"),
    bg="White",
    fg="Black",
    pady=6
)
maze_label.pack(fill="x")

canvas = turtle.ScrolledCanvas(border_frame, width=600, height=600)
canvas.config(highlightthickness=0, bd=0, relief="flat")
canvas.pack()
screen = turtle.TurtleScreen(canvas)
screen.tracer(0)   # manual updates

# Maze drawing turtle
maze = turtle.RawTurtle(screen)
maze.speed(0)
maze.hideturtle()

# Player turtle
player = turtle.RawTurtle(screen)
player.shape("turtle")
player.color("blue")
player.penup()

# Goal marker
goal_marker = turtle.RawTurtle(screen)
goal_marker.shape("circle")
goal_marker.color("green")
goal_marker.penup()

# Globals
walls = []
start_pos = (0, 0)
goal_pos = (0, 0)
maze_name = ""

total_moves_all = 0
total_distance_all = 0.0
total_score_all = 0.0

def get_username():
    global PLAYER_USERNAME
    
    # Check if a username has been set, otherwise prompt the user
    if not PLAYER_USERNAME:
        username = simpledialog.askstring("Username", "Enter your unique competition username:")
        if username:
            PLAYER_USERNAME = username.strip()
            # Update the UI element to show the player who they are
            status_label.config(text=f"Welcome, {PLAYER_USERNAME}!\nStatus: Ready")
        else:
            # Handle cancel or no input
            PLAYER_USERNAME = "Anonymous"
            status_label.config(text="Status: Ready (Anonymous Player)")

# --- Border Color SET ---
def set_border_color(color):
    border_frame.config(highlightbackground=color)
    border_frame.update()

# --- Maze Loader ---
def build_maze(filename):
    global walls, start_pos, goal_pos, maze_name
    maze.clear()
    walls.clear()
    with open(filename, "r") as f:
        data = json.load(f)
    walls = data["walls"]
    start_pos = tuple(data["start"])
    goal_pos = tuple(data["goal"])
    maze_name = data["name"]
    maze_label.config(text=maze_name)
    for wall in walls:
        x1, y1, x2, y2 = wall
        maze.penup()
        maze.goto(x1, y1)
        maze.pendown()
        maze.goto(x2, y2)
    player.clear()
    player.penup()
    player.goto(start_pos)
    player.setheading(0)
    goal_marker.clearstamps()
    goal_marker.goto(goal_pos)
    goal_marker.stamp()
    screen.update()


# --- Maze Progression ---
def load_next_maze():
    global current_maze_index, timer_running
    set_border_color("white")
    timer_running = False
    current_maze_index += 1
    if current_maze_index < len(maze_files):
        text_box.delete("1.0", tk.END)
        build_maze(maze_files[current_maze_index])
        status_label.config(text=f"Next Maze Loaded! 🧩 Maze {current_maze_index + 1}")
        start_timer()  # start fresh timer for new maze
    else:   
        show_final_scores()


def show_final_scores():
    timer_running = False
    summary = "🏁 All Mazes Completed!\n\nYour Scores:\n"
    for maze_name, score in scores.items():
        summary += f"• {maze_name}: {score:.2f}\n"
    summary += f"\nTotal Score: {total_score_all:.2f}\n\n🎯 Well done!"
    msg.showinfo("Results", summary)


# --- Collision Detection ---
def is_collision(x, y):
    THRESHOLD = 5
    for x1, y1, x2, y2 in walls:
        dx = x2 - x1
        dy = y2 - y1
        len_sq = dx * dx + dy * dy
        if len_sq == 0:
            if math.hypot(x - x1, y - y1) < THRESHOLD:
                return True
            continue
        t = ((x - x1) * dx + (y - y1) * dy) / len_sq
        t = max(0, min(1, t))
        closest_x = x1 + t * dx
        closest_y = y1 + t * dy
        distance = math.hypot(x - closest_x, y - closest_y)
        if distance < THRESHOLD:
            return True
    return False


# --- Timer ---
def start_timer():
    global start_time, timer_running
    start_time = time.time()
    timer_running = True
    update_timer()


def update_timer():
    if timer_running:
        elapsed = time.time() - start_time
        timer_label.config(text=f"⏱ Time: {int(elapsed)}s")
        root.after(1000, update_timer)


# --- Command Execution ---
def run_commands():
    global start_time, timer_running, total_time_all, total_moves_all, total_distance_all, total_score_all, maze_name
    move_count = 0
    total_distance = 0

    set_border_color("white")
    player.clear()
    player.penup()
    player.goto(start_pos)
    player.pendown()
    player.setheading(0)
    screen.update()

    commands = text_box.get("1.0", tk.END).strip().splitlines()

    for cmd in commands:
        parts = cmd.strip().split()
        if not parts:
            continue
        action = parts[0].upper()
        move_count += 1
        if action == "MOVE" and len(parts) == 2:
            try:
                dist = int(parts[1])
                total_distance += abs(dist)
                step = 5
                for _ in range(abs(dist)//step):
                    player.forward(step if dist > 0 else -step)
                    screen.update()
                    time.sleep(0.02)
                    if is_collision(player.xcor(), player.ycor()):
                        player.backward(step)
                        status_label.config(text="💥 Hit a wall! Try again.")
                        set_border_color("red")
                        return
                    if player.distance(goal_pos) < 20:
                        elapsed = time.time() - start_time
                        score = max(100, 1000 - (elapsed * 0.8 + move_count * 3 + total_distance * 0.2))
                        scores[f"{maze_name}"] = score
                        print(scores)
                        set_border_color("green")
                        timer_running = False
                        total_moves_all += move_count
                        total_distance_all += total_distance
                        total_score_all += score
                        status_label.config(
                            text=f"{maze_name} Complete!\n"
                        )
                        score_label.config(
                            text=f"⏱ Prev. Maze Time: {elapsed:.2f}s\n🚶 Moves: {total_moves_all}\n📏 Distance: {int(total_distance_all)}\n🏆 Score: {total_score_all:.2f}"
                        )
                        screen.update()
                        if PLAYER_USERNAME == "" or PLAYER_USERNAME == "Anonymous":
                            print("Score not submitted: Anonymous player.")
                            pass 
                        else:
                            status_label.config(
                                text=f"{maze_name} Complete! Uploading score\n"
                            )
                            screen.update()
                            status_label.config(
                                text=f"{maze_name} Complete! Uploaded\n"
                            )
                        if current_maze_index == len(maze_files) - 1:
                            # final maze — show final scores after a short pause so user can read
                            root.after(1500, show_final_scores)
                        else:
                            # not last one — go to next maze after a short pause
                            root.after(2000, load_next_maze)
                        return
            except:
                pass
        elif action == "TURN" and len(parts) == 2:
            try:
                angle = int(parts[1])
                player.right(angle)
                screen.update()
                time.sleep(0.1)
            except:
                pass
    status_label.config(text="✅ Finished commands")


# --- UI ELEMENTS ---
timer_label = tk.Label(frame_left, text="⏱ Time: 0.0s", font=("Consolas", 11, "bold"))
timer_label.pack(pady=5)
root.bind('<Control-Return>', lambda event: run_commands())

score_label = tk.Label(frame_left, text="🏆 Score: —", font=("Consolas", 11, "bold"))
score_label.pack(pady=5)

label = tk.Label(frame_left, text="Enter commands:")
label.pack()

text_box = tk.Text(frame_left, height=15, width=25)
text_box.pack()

run_button = tk.Button(frame_left, text="▶ Run", command=run_commands)
run_button.pack(pady=5)

status_label = tk.Label(frame_left, text="Status: Ready", justify="left", wraplength=250)
status_label.pack()

# --- INSTRUCTION PANEL ---
def show_instructions():
    instructions = """
📘 **INSTRUCTIONS**

Welcome to the Maze Solver challenge! 🧩  
Your goal is to navigate the blue turtle 🐢from the start point to the green goal 🟢
using text-based movement commands — without hitting any walls.

───────────────────────────────
🧭 **COMMANDS**
───────────────────────────────
➡️ MOVE <distance>  
- Moves the turtle forward by the given number of pixels.

↩️ TURN <angle>  
- Rotates the turtle clockwise by the given number of degrees.
- Rotates Anti Clockwise by using negative number of degrees.

───────────────────────────────
💻 **EXAMPLES**
───────────────────────────────
TURN 120
MOVE 220
TURN -120
MOVE 240
TURN 55
MOVE 70 

───────────────────────────────
🎯 **GOAL**
───────────────────────────────
✅ Reach the green circle without touching any walls.  
💥 Colliding with a wall ends your attempt.  
🏁 The faster you reach the goal with fewer moves and less distance, the higher your score!

───────────────────────────────
🕹️ **SCORING SYSTEM**
───────────────────────────────
🏆 Final Score is calculated from:
- ⏱️ Time taken  
- 🚶 Number of moves (commands)  
- 📏 Total distance traveled  

Higher scores = better performance!

───────────────────────────────
💡 **HINTS**
───────────────────────────────
- Try smaller moves for precision.
- Use right angles (90°) for sharp turns.
- Plan your path before executing commands.

Good luck, maze solver! 🎉
"""
    help_window = tk.Toplevel()
    help_window.title("📘 Instructions")
    help_window.geometry("450x500")
    help_window.resizable(False, True)

    text_widget = tk.Text(help_window, wrap="word", font=("Consolas", 11), bg="#f8f9fa")
    text_widget.insert("1.0", instructions)
    text_widget.config(state="disabled")
    text_widget.pack(expand=True, fill="both", padx=10, pady=10)

    scrollbar = tk.Scrollbar(help_window, command=text_widget.yview)
    scrollbar.pack(side="right", fill="y")
    text_widget.config(yscrollcommand=scrollbar.set)


help_button = tk.Button(frame_left, text="❓ Help / Instructions", command=show_instructions)
help_button.pack(pady=5)

get_username()

# Build first maze and start timer
build_maze(maze_files[current_maze_index])
start_timer()

root.mainloop()
