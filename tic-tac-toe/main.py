def print_board(board):
    print("\n")
    print(f" {board[0]} | {board[1]} | {board[2]} ")
    print("---|---|---")
    print(f" {board[3]} | {board[4]} | {board[5]} ")
    print("---|---|---")
    print(f" {board[6]} | {board[7]} | {board[8]} ")
    print("\n")

def check_win(board, player):
    win_conditions = [
        [0, 1, 2], [3, 4, 5], [6, 7, 8], # Rows
        [0, 3, 6], [1, 4, 7], [2, 5, 8], # Columns
        [0, 4, 8], [2, 4, 6]             # Diagonals
    ]
    for condition in win_conditions:
        if board[condition[0]] == board[condition[1]] == board[condition[2]] == player:
            return True
    return False

def check_draw(board):
    return " " not in board

def main():
    print("Welcome to Tic-Tac-Toe!")
    board = [" " for _ in range(9)]
    current_player = "X"
    
    while True:
        print_board(board)
        print(f"Player {current_player}'s turn.")
        
        try:
            move = int(input("Enter a position (1-9): ")) - 1
            if move < 0 or move > 8:
                print("Invalid input! Please enter a number between 1 and 9.")
                continue
            if board[move] != " ":
                print("That position is already taken! Try again.")
                continue
        except ValueError:
            print("Invalid input! Please enter a valid number.")
            continue
            
        board[move] = current_player
        
        if check_win(board, current_player):
            print_board(board)
            print(f"Congratulations! Player {current_player} wins!")
            break
            
        if check_draw(board):
            print_board(board)
            print("It's a draw!")
            break
            
        current_player = "O" if current_player == "X" else "X"

if __name__ == "__main__":
    main()
