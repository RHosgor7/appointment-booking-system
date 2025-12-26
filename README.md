# Appointment Booking System

Multi-tenant online appointment booking system built with FastAPI, MySQL, and Metronic UI.

## 🚀 Features

- 🔐 **JWT Authentication** - Secure token-based authentication
- 👥 **Role-based Authorization** - Owner, Admin, and Staff roles with granular permissions
- 🏢 **Multi-tenant Architecture** - Complete data isolation per business
- 📅 **Appointment Management** - Full CRUD with double-booking prevention
- 👤 **Customer Management** - Customer profiles and history
- 💼 **Staff Management** - Staff profiles with optional panel access
- 🎯 **Service Management** - Service catalog with pricing
- 💰 **Transaction Management** - Payment tracking with idempotency
- 🔗 **Public Booking Links** - Shareable booking links for customers
- 📊 **Dashboard** - Overview and analytics
- ⚙️ **Business Settings** - Configurable slot length, buffer time, working hours

## 🛠️ Tech Stack

- **Backend**: FastAPI (Python 3.11+)
- **Database**: MySQL 8.0+
- **Frontend**: Jinja2 Templates with Metronic UI
- **Authentication**: JWT (JSON Web Tokens)
- **Password Hashing**: bcrypt

## 📋 Prerequisites

- Python 3.11 or higher
- MySQL 8.0 or higher
- pip (Python package manager)

## 🔧 Installation

### 1. Clone the Repository

```bash
git clone https://github.com/YOUR_USERNAME/appointment-booking-system.git
cd appointment-booking-system/demo
```

### 2. Create Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Database Setup

```bash
# Create database
mysql -u root -p
CREATE DATABASE appointment_booking CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
EXIT;

# Run schema
mysql -u root -p appointment_booking < migrations/schema.sql

# (Optional) Seed with sample data
mysql -u root -p appointment_booking < scripts/seed.sql
```

### 5. Environment Configuration

Create `.env` file in `demo/` directory:

```env
# Database
DB_HOST=localhost
DB_PORT=3306
DB_USER=root
DB_PASSWORD=your_password
DB_NAME=appointment_booking

# JWT
JWT_SECRET_KEY=your-secret-key-here-change-in-production
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

### 6. Run the Application

```bash
cd demo
uvicorn app.main:app --reload --port 8000
```

The application will be available at:
- **API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs
- **Web Interface**: http://localhost:8000/login

## 📚 API Documentation

Once the server is running, visit:
- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc

## 🔐 Default Credentials

After seeding the database, you can login with:
- **Email**: owner@test.com
- **Password**: (check seed.sql for password)

## 📁 Project Structure

```
demo/
├── app/
│   ├── api/
│   │   └── routers/      # API endpoints
│   ├── models/
│   │   └── schemas.py   # Pydantic models
│   ├── services/        # Business logic
│   ├── templates/       # Jinja2 templates
│   ├── static/          # Static files (CSS, JS, images)
│   ├── auth.py          # JWT & password hashing
│   ├── config.py        # Configuration
│   ├── db.py            # Database connection
│   ├── dependencies.py   # FastAPI dependencies
│   └── main.py          # Application entry point
├── migrations/
│   └── schema.sql       # Database schema
├── scripts/
│   └── seed.sql         # Sample data
└── requirements.txt      # Python dependencies
```

## 🧪 Testing

```bash
# Run tests (if available)
pytest

# Or manually test via API
curl http://localhost:8000/health
```

## 📖 Documentation

- **Database Security**: See `md/DATABASE_SECURITY.md`
- **Static Media Usage**: See `md/STATIC_MEDIA_USAGE.md`
- **Project Roadmap**: See `md/ROADMAP.md`
- **GitHub Setup**: See `md/GITHUB_SETUP.md`

## 🔒 Security Features

- Multi-tenant data isolation (business_id filtering)
- JWT token-based authentication
- Role-based access control (Owner/Admin/Staff)
- Password hashing with bcrypt
- SQL injection prevention (parameterized queries)
- Double-booking prevention
- Idempotency for transactions
- Race condition prevention (staff_day_locks)

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add some amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📝 License

This project is for educational purposes (BLG317E course).

## 👨‍💻 Author

BLG317E - Appointment Booking System Project

## 📞 Support

For issues and questions, please open an issue on GitHub.

---

**Version**: 1.0.0  
**Last Updated**: December 2025

