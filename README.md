# Voyager 2 Reminder 🚀

A FastAPI-based web service that emails you as NASA's Voyager 1 and Voyager 2 travel farther from the Sun. Users register with their preferred distance unit (light-seconds, light-minutes, or light-hours), and every update also shows how long each spacecraft's signal takes to reach Earth.

Updates are triggered by distance from the Sun, which only ever grows. Distance from Earth rises and falls with Earth's orbit, so it would stall the emails for months each year. It is still used for the signal time in each email, and for a one-off email whenever a spacecraft passes a new light-day from Earth.

## Features

- 📧 **Email Notifications**: Automated email alerts for Voyager 1 and Voyager 2
- 📏 **Multiple Distance Units**: Choose from light-seconds, light-minutes, or light-hours  
- 📡 **Live Contact**: Shows which Deep Space Network dish is receiving the spacecraft
- ⏰ **Scheduled Jobs**: Background scheduler for automated notifications
- 🐋 **Docker Support**: Easy deployment with Docker and Docker Compose
- ☁️ **Cloud Ready**: Configured for Fly.io deployment

## API Endpoints

### User Management
- `POST /register` - Register a new user
- `GET /verify?token=...` - Confirm a registration from the emailed link

### Notifications
- `GET /unsubscribe?token=...` - Unsubscribe confirmation page (linked from every update email)
- `POST /unsubscribe?token=...` - Unsubscribe; also handles one-click requests from mail clients

### Scheduler
- `GET /jobs` - Get scheduled jobs information

## Quick Start

### Prerequisites
- Python 3.11+
- Docker (optional)

### Local Development

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/voyager2-reminder.git
   cd voyager2-reminder
   ```

2. **Create virtual environment**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set up environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your email configuration
   ```

5. **Run the application**
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
   ```

6. **Access the API**
   - API: http://localhost:8080
   - Interactive docs: http://localhost:8080/docs
   - ReDoc: http://localhost:8080/redoc

### Docker Development

1. **Using Docker Compose (Recommended)**
   ```bash
   docker-compose up --build
   ```

2. **Using Docker directly**
   ```bash
   docker build -t voyager2-reminder .
   docker run -p 8000:8080 --env-file .env voyager2-reminder
   ```

## Configuration

Create a `.env` file in the root directory:

```env
# Email Configuration
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
EMAIL_ADDRESS=your-email@gmail.com
EMAIL_PASSWORD=your-app-password

# API Configuration  
API_HOST=0.0.0.0
API_PORT=8080

# Database
DATABASE_URL=sqlite:///./data/users.db

# Scheduler
SCHEDULER_INTERVAL_MINUTES=60
```

## API Usage Examples

### Register a User
```bash
curl -X POST "http://localhost:8080/register" \
     -H "Content-Type: application/json" \
     -d '{
       "email": "user@example.com",
       "unit": "light_minute"
     }'
```

## Distance Units

- **`light_second`**: Distance light travels in one second (~299,792,458 meters)
- **`light_minute`**: Distance light travels in one minute (~17.99 billion meters)  
- **`light_hour`**: Distance light travels in one hour (~1.08 trillion meters)

## Deployment

### Fly.io Deployment

1. **Install Fly CLI**
   ```bash
   # macOS
   brew install flyctl
   
   # Windows
   powershell -Command "iwr https://fly.io/install.ps1 -useb | iex"
   ```

2. **Login and Deploy**
   ```bash
   fly auth login
   fly deploy
   ```

3. **Set Environment Variables**
   ```bash
   fly secrets set SMTP_SERVER=smtp.gmail.com
   fly secrets set EMAIL_ADDRESS=your-email@gmail.com
   fly secrets set EMAIL_PASSWORD=your-app-password
   ```

### Other Platforms

The application is containerized and can be deployed on:
- **Heroku**: Use the included Dockerfile
- **AWS ECS/Fargate**: Deploy the Docker image
- **Google Cloud Run**: Deploy the container
- **DigitalOcean App Platform**: Connect your GitHub repo

## Project Structure

```
voyager2-reminder/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── models.py            # SQLAlchemy models
│   ├── database.py          # Database configuration
│   ├── scheduler.py         # Background job scheduler
│   ├── emailer.py           # Email notification logic
│   └── distance_fetcher.py  # JPL Horizons and DSN lookups
├── data/
│   └── users.db             # SQLite database
├── requirements.txt         # Python dependencies
├── Dockerfile              # Container configuration
├── docker-compose.yml      # Multi-container setup
├── fly.toml                # Fly.io deployment config
└── README.md               # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## Technologies Used

- **[FastAPI](https://fastapi.tiangolo.com/)** - Modern, fast web framework for building APIs
- **[SQLAlchemy](https://www.sqlalchemy.org/)** - SQL toolkit and ORM
- **[APScheduler](https://apscheduler.readthedocs.io/)** - Advanced Python Scheduler
- **[Pydantic](https://pydantic.dev/)** - Data validation using Python type hints
- **[Uvicorn](https://www.uvicorn.org/)** - Lightning-fast ASGI server

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- NASA for the Voyager mission data
- The open-source community for the amazing tools and libraries

---

**Made with ❤️ for space enthusiasts and Python developers** 