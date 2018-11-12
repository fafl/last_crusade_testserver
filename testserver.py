import sys
import time
from enum import auto, Enum
from subprocess import PIPE, Popen

LEVEL_FILES = [
    # Level 2
    'broken_well.in',
    'broken_sewer.in',
    'broken_secret_passages.in',
    'broken_mausoleum.in',
    'underground_complex.in',
    'rocks_1.in',
    'rocks_2.in',

    # Level 3
    'avoiding_rocks.in',
    'rock_interception.in',
    'multiple_choice_and_rocks.in',
    'only_one_way.in',

    # Custom
    'only_one_way_validator.in',
]


class Dir(Enum):
    TOP = auto()
    BOT = auto()
    LEFT = auto()
    RIGHT = auto()
    CRASH = auto()

    def opposite(self):
        if self == Dir.TOP:
            return Dir.BOT
        elif self == Dir.BOT:
            return Dir.TOP
        elif self == Dir.LEFT:
            return Dir.RIGHT
        elif self == Dir.RIGHT:
            return Dir.LEFT
        else:
            raise ValueError('No opposite exists for ' + self.name)

    def get_new_coordinates(self, x, y):
        if self == Dir.BOT:
            return x, y + 1
        elif self == Dir.LEFT:
            return x - 1, y
        elif self == Dir.RIGHT:
            return x + 1, y
        else:
            raise ValueError('Cannot exit room in direction ' + self.name)


# Room layouts with {enterDirection: exitDirection}
TURNS = [
    {},  # 0
    {Dir.TOP: Dir.BOT, Dir.LEFT: Dir.BOT, Dir.RIGHT: Dir.BOT},  # 1
    {Dir.LEFT: Dir.RIGHT, Dir.RIGHT: Dir.LEFT},  # 2
    {Dir.TOP: Dir.BOT},  # 3
    {Dir.TOP: Dir.LEFT, Dir.RIGHT: Dir.BOT, Dir.LEFT: Dir.CRASH},  # 4
    {Dir.TOP: Dir.RIGHT, Dir.LEFT: Dir.BOT, Dir.RIGHT: Dir.CRASH},  # 5
    {Dir.LEFT: Dir.RIGHT, Dir.RIGHT: Dir.LEFT, Dir.TOP: Dir.CRASH},  # 6
    {Dir.TOP: Dir.BOT, Dir.RIGHT: Dir.BOT},  # 7
    {Dir.LEFT: Dir.BOT, Dir.RIGHT: Dir.BOT},  # 8
    {Dir.TOP: Dir.BOT, Dir.LEFT: Dir.BOT},  # 9
    {Dir.TOP: Dir.LEFT, Dir.LEFT: Dir.CRASH},  # 10
    {Dir.TOP: Dir.RIGHT, Dir.RIGHT: Dir.CRASH},  # 11
    {Dir.RIGHT: Dir.BOT},  # 12
    {Dir.LEFT: Dir.BOT}  # 13
]

# Room rotations with Room ID -> [CCW, CW]
ROTATIONS = {
    1: [1, 1],
    2: [3, 3],
    3: [2, 2],
    4: [5, 5],
    5: [4, 4],
    6: [9, 7],
    7: [6, 8],
    8: [7, 9],
    9: [8, 6],
    10: [13, 11],
    11: [10, 12],
    12: [11, 13],
    13: [12, 10]
}


def debug(*args):
    print(*args, file=sys.stderr)


def read_state(p):
    state = p.stdout.readline().decode('utf8').rstrip()
    print('<-', state)
    return state


def send_data(p, data):
    print('->', data)
    p.stdin.write((str(data) + '\n').encode('utf8'))
    p.stdin.flush()


def send_state(p, t, indy, rocks):
    send_data(p, f'{indy[0]} {indy[1]} {indy[2].name}')
    visible_rocks = [r for r in rocks if r[3] <= t]
    send_data(p, f'{len(visible_rocks)}')
    for rock in visible_rocks:
        send_data(p, f'{rock[0]} {rock[1]} {rock[2].name}')


def apply_decision(maze, decision, indy, rocks):
    if decision == 'WAIT':
        return
    x, y, rotation = decision.split()
    x = int(x)
    y = int(y)
    indy_x, indy_y, _ = indy
    if (x, y) == (indy_x, indy_y):
        raise ValueError(f'Unable to rotate room with indy inside at {x} {y}')
    for rock in rocks:
        rock_x, rock_y, _, _ = rock
        if (x, y) == (rock_x, rock_y):
            raise ValueError(f'Unable to rotate room with a rock inside at {x} {y}')
    room = maze[y][x]
    if room < 1:
        raise ValueError(f'Room {x} {y} has layout {room} and can not be rotated')
    if rotation not in ['LEFT', 'RIGHT']:
        raise ValueError(f'Rotation must be either LEFT or RIGHT but is {rotation}')
    new_room = ROTATIONS[room][rotation == 'RIGHT']
    maze[int(y)][int(x)] = new_room


def tick(maze, maze_exit, t, indy, rocks):
    w = len(maze[0])
    h = len(maze)

    # Move indy
    x, y, entry_dir = indy
    room = maze[y][x]
    exit_dir = TURNS[abs(room)][entry_dir]
    if exit_dir == Dir.CRASH:
        raise ValueError(f'Indy has no exit from room {x} {y}')
    new_x, new_y = exit_dir.get_new_coordinates(x, y)
    new_entry_dir = exit_dir.opposite()
    new_room = maze[new_y][new_x]
    if new_entry_dir in TURNS[abs(new_room)]:
        indy = (new_x, new_y, new_entry_dir)
    else:
        raise ValueError(f'Indy crashed into the wall of room {new_x} {new_y}')
    if (new_x, new_y) == maze_exit:
        print(f'Indy has reached the exit at {new_x} {new_y}')
        return None, None, True

    # Keep track of rocks to eliminate
    eliminated_rocks = set()
    prev_rock_positions = []

    # Move rocks
    for r, rock in enumerate(rocks):
        rock_x, rock_y, entry_dir, from_t = rock
        prev_rock_positions.append((rock_x, rock_y))
        if t < from_t:
            # Inactive rock
            continue
        room = maze[rock_y][rock_x]
        exit_dir = TURNS[abs(room)][entry_dir]
        new_entry_dir = exit_dir.opposite()
        new_rock_x, new_rock_y = exit_dir.get_new_coordinates(rock_x, rock_y)
        if not (0 <= new_rock_x < w and 0 <= new_rock_y < h):
            # Rock left the maze
            eliminated_rocks.add(r)
            continue
        new_room = maze[new_rock_y][new_rock_x]
        if new_entry_dir in TURNS[abs(new_room)]:
            rocks[r] = (new_rock_x, new_rock_y, new_entry_dir, from_t)
        else:
            print(f'Rock entering {new_rock_x} {new_rock_y} from {new_entry_dir.name} crashed into a wall')
            eliminated_rocks.add(r)
            continue

        # Check crash with indy
        if (new_x, new_y) == (new_rock_x, new_rock_y) or (
            (x, y) == (new_rock_x, new_rock_y) and (new_x, new_y) == (rock_x, rock_y)
        ):
            raise ValueError(f'Indy crashed into a rock in room {new_x} {new_y}')

    # Check rocks crashing into each other
    for r1 in range(len(rocks) - 1):
        x1, y1, _, from_t = rocks[r1]
        if t < from_t:
            # Inactive rock
            continue
        x1prev, y1prev = prev_rock_positions[r1]
        for r2 in range(r1 + 1, len(rocks)):
            x2, y2, _, from_t = rocks[r2]
            if t < from_t:
                # Inactive rock
                continue
            x2prev, y2prev = prev_rock_positions[r2]
            if (x1, y1) == (x2, y2):
                print(f'Rocks from {x1prev} {y1prev} and {x2prev} {y2prev} will crash in {x1} {y1}')
                eliminated_rocks.add(r1)
                eliminated_rocks.add(r2)
                break
            if (x1, y1) == (x2prev, y2prev) and (x1prev, y1prev) == (x2, y2):
                print(f'Rocks from {x1prev} {y1prev} and {x2prev} {y2prev} will crash into each other')
                eliminated_rocks.add(r1)
                eliminated_rocks.add(r2)
                break

    # Remove rocks that will have no exit
    for r, rock in enumerate(rocks):
        rock_x, rock_y, entry_dir, from_t = rock
        room = maze[rock_y][rock_x]
        if TURNS[abs(room)][entry_dir] == Dir.CRASH:
            eliminated_rocks.add(r)

    # Eliminate rocks from the game
    for r in reversed(sorted(eliminated_rocks)):
        rocks.pop(r)

    return indy, rocks, False


def run_testcase(input_path, p):

    with open('./levels/' + input_path) as f:
        lines = f.readlines()

    w, h = map(int, lines.pop(0).split())
    maze = []
    for i in range(h):
        maze.append([int(x) for x in lines.pop(0).split()])
    maze_exit = (int(lines.pop(0)), h - 1)

    indy = lines.pop(0).split()
    indy[0] = int(indy[0])
    indy[1] = int(indy[1])
    indy[2] = Dir[indy[2]]

    rock_count = int(lines.pop(0))
    rocks = []
    for i in range(rock_count):
        rock = lines.pop(0).split()
        rock[0] = int(rock[0])
        rock[1] = int(rock[1])
        rock[2] = Dir[rock[2]]
        rock[3] = int(rock[3])
        rocks.append(rock)

    assert not lines

    # Send maze
    time.sleep(0.5)  # Give some startup time before sending the maze
    send_data(p, f'{w} {h}')
    for row in maze:
        send_data(p, ' '.join(map(str, row)))
    send_data(p, f'{maze_exit[0]}')

    # Play until done
    is_indy_at_exit = False
    now = start_time = time.time()
    longest_turn = 0
    for t in range(1000):
        send_state(p, t, indy, rocks)
        try:
            decision = read_state(p)
            last = now
            now = time.time()
            if last != 0:
                longest_turn = max(longest_turn, now - last)
            print(f't is {t} and time elapsed is {now - start_time}')
            apply_decision(maze, decision, indy, rocks)
            indy, rocks, is_indy_at_exit = tick(maze, maze_exit, t, indy, rocks)
            if is_indy_at_exit:
                break

        except ValueError as e:
            print(e)
            return False, now - start_time, longest_turn

    return True, now - start_time, longest_turn


def main():
    command = sys.argv[1:]
    runs = []
    for level in LEVEL_FILES:
        print(f'Running level {level}')
        with open('stderr.out', 'w') as stderr_out_file:

            # Start child process
            print(f'Running command: {command}')
            p = Popen(command, stdin=PIPE, stdout=PIPE, stderr=stderr_out_file)

            # Play a game
            is_success, time_taken, longest_turn = run_testcase(level, p)
            runs.append((level, is_success, time_taken, longest_turn))
            p.kill()

    print('Summary:')
    for level, is_success, time_taken, longest_turn in runs:
        print('*', 'Success' if is_success else 'Fail', 'in', '{:.3f}'.format(time_taken), 'seconds in level', level)
        if 0.14 < longest_turn:
            print('  * Longest turn was slow at', '{:.3f}'.format(longest_turn), 'seconds')


if __name__ == '__main__':
    main()
