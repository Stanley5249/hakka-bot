# Hakka bot

## Project Overview

This project is a chat application built with Python. It uses the FastAPI framework and consists of two main files:

1. `main.py`: This is the main entry point of the application.
2. `chat.py`: This file contains the implementation of the chat functionality, including classes for handling chat messages, actions, and transitions.

## Installation Guide

Follow these steps to install and run the project:

1. Clone the repository to your local machine.

```sh
git clone "https://github.com/Stanley5249/hakka-bot.git"
```

2. Navigate to the project directory.

```sh
cd hakka-bot
```

3. Install the required Python packages. It's recommended to use a virtual environment.

```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running the Application

To start the application, use the following command:

```sh
fastapi run app/main.py
```

This will start the FastAPI server and the application will be accessible at `http://localhost:8000`.

## Contributing

Contributions are welcome! Please read the contributing guide for more information.

## License

This project is licensed under the terms of the MIT license.