from app.database.schema import User
from sqlalchemy.orm import Session

class UserService:
    def __init__(self, db: Session):
        self.db = db

    def get_or_create_from_google(self, google_id, email, name, picture=None):
        user = self.db.query(User).filter(User.google_id == google_id).first()

        if not user:
            user = self.db.query(User).filter(User.email == email).first()
            if user:
                user.google_id = google_id
                user.picture = picture
                self.db.commit()
                self.db.refresh(user)

        if not user:
            user = User(google_id=google_id, email=email, name=name, picture=picture)
            self.db.add(user)
            self.db.commit()
            self.db.refresh(user)

        return user



