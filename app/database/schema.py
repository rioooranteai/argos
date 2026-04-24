from sqlalchemy import Column, Integer, String
from sqlalchemy.ext.declarative import declarative_base

Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    google_id = Column(String, unique=True, nullable=True)
    email = Column(String, unique=True, nullable=True)
    name = Column(String)
    picture = Column(String, nullable=True)
