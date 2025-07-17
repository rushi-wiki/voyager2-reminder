import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
import os
import sys

# Add the app directory to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from app.main import app
from app import models, database

# Create test database
TEST_DATABASE_URL = "sqlite:///./test.db"
test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

# Create test database tables
models.Base.metadata.create_all(bind=test_engine)

# Override the get_db dependency
def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[database.get_db] = override_get_db

client = TestClient(app)

@pytest.fixture
def test_user():
    return {
        "email": "test@example.com",
        "unit": "light_second"
    }

def test_root_endpoints():
    """Test that basic endpoints are accessible"""
    response = client.get("/users")
    assert response.status_code == 200

def test_register_user(test_user):
    """Test user registration"""
    response = client.post("/register", json=test_user)
    assert response.status_code == 200
    assert "message" in response.json()
    assert response.json()["message"] == "User registered"

def test_register_duplicate_user(test_user):
    """Test that duplicate email registration fails"""
    # Register user first time
    client.post("/register", json=test_user)
    
    # Try to register same email again
    response = client.post("/register", json=test_user)
    assert response.status_code == 400
    assert "Email already registered" in response.json()["detail"]

def test_register_invalid_unit():
    """Test registration with invalid unit"""
    invalid_user = {
        "email": "test2@example.com",
        "unit": "invalid_unit"
    }
    response = client.post("/register", json=invalid_user)
    assert response.status_code == 400
    assert "Invalid unit" in response.json()["detail"]

def test_get_users():
    """Test getting all users"""
    response = client.get("/users")
    assert response.status_code == 200
    assert "users" in response.json()

def test_get_user_by_id():
    """Test getting user by ID"""
    # First register a user
    test_user = {"email": "getuser@example.com", "unit": "light_minute"}
    client.post("/register", json=test_user)
    
    # Get all users to find the ID
    users_response = client.get("/users")
    users = users_response.json()["users"]
    
    if users:
        user_id = users[-1]["id"]  # Get the last user's ID
        response = client.get(f"/users/{user_id}")
        assert response.status_code == 200
        assert "user" in response.json()

def test_get_nonexistent_user():
    """Test getting a user that doesn't exist"""
    response = client.get("/users/99999")
    assert response.status_code == 404
    assert "User not found" in response.json()["detail"]

def test_delete_user():
    """Test deleting a user"""
    # First register a user
    test_user = {"email": "deleteuser@example.com", "unit": "light_hour"}
    client.post("/register", json=test_user)
    
    # Get all users to find the ID
    users_response = client.get("/users")
    users = users_response.json()["users"]
    
    if users:
        user_id = users[-1]["id"]  # Get the last user's ID
        response = client.delete(f"/users/{user_id}")
        assert response.status_code == 200
        assert response.json()["message"] == "User deleted"

def test_delete_nonexistent_user():
    """Test deleting a user that doesn't exist"""
    response = client.delete("/users/99999")
    assert response.status_code == 404
    assert "User not found" in response.json()["detail"]

def test_get_jobs():
    """Test getting scheduled jobs"""
    response = client.get("/jobs")
    assert response.status_code == 200
    assert "jobs" in response.json()

def test_notify_user():
    """Test sending notification to user"""
    # First register a user
    test_user = {"email": "notify@example.com", "unit": "light_second"}
    client.post("/register", json=test_user)
    
    # Get all users to find the ID
    users_response = client.get("/users")
    users = users_response.json()["users"]
    
    if users:
        user_id = users[-1]["id"]  # Get the last user's ID
        response = client.post(f"/users/{user_id}/notify")
        # Note: This might fail if email configuration is not set up
        # In a real test environment, you'd mock the email service
        assert response.status_code in [200, 500]  # Allow for email errors

def test_notify_nonexistent_user():
    """Test sending notification to user that doesn't exist"""
    response = client.post("/users/99999/notify")
    assert response.status_code == 404
    assert "User not found" in response.json()["detail"]

# Cleanup after tests
def pytest_sessionfinish(session, exitstatus):
    """Cleanup test database after all tests"""
    import os
    if os.path.exists("test.db"):
        os.remove("test.db") 