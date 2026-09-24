from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

# Remplacez 'votre_mot_de_passe' par votre mot de passe PostgreSQL local
SQLALCHEMY_DATABASE_URL = "postgresql://postgres:justin123@localhost:5432/juridique_db"

engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Dependance pour ouvrir et fermer la session BDD a chaque requete
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()