from mongomock import MongoClient
import unittest
import pytest
from app.authentication import AuthenticationService
import hashlib
from fastapi import HTTPException


class TestAuthenticationService(unittest.TestCase):

    def setUp(self):
        # Mocking the database using mongomock
        self.db = MongoClient().db
        self.secret_key = "secret"
        self.token_expire_minutes = 30
        self.auth_service = AuthenticationService(self.db, self.secret_key, self.token_expire_minutes)

    def test_authenticate_success(self):
        # Add users data to the mocked DB
        self.db.users.insert_one({
            "_id": "123",
            "name": "test",
            "hashed_password": hashlib.sha256("test_password".encode()).hexdigest()
        })

        token = self.auth_service.authenticate("test", "test_password")
        assert isinstance(token, str)

    def test_authenticate_fail_user_not_found(self):
        with pytest.raises(HTTPException):
            self.auth_service.authenticate("nonexistent", "password")

    def test_authenticate_fail_incorrect_password(self):
        # Add users data to the mocked DB
        self.db.users.insert_one({
            "_id": "123",
            "name": "test",
            "hashed_password": hashlib.sha256("test_password".encode()).hexdigest()
        })

        with pytest.raises(HTTPException):
            self.auth_service.authenticate("test", "wrong_password")
