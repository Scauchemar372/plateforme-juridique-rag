# main.py - API Backend FastAPI avec support du chat interactif et stockage de l'historique

import os
import json
from datetime import datetime
import requests
from fastapi import FastAPI, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from sqlalchemy import Column, Integer, String, Text, DateTime
from pydantic import BaseModel, EmailStr
import pypdf

from langchain_text_splitters import RecursiveCharacterTextSplitter
import chromadb

from database import engine, Base, get_db
from auth import hash_password, verify_password, create_access_token, get_current_user_data
from chromadb.utils import embedding_functions

app = FastAPI(title="Plateforme Juridique - RAG")

DOSSIER_STOCKAGE = "./contrats_upload"
os.makedirs(DOSSIER_STOCKAGE, exist_ok=True)

chroma_client = chromadb.PersistentClient(path="./chroma_db")

# On définit Ollama comme moteur de vectorisation
ollama_ef = embedding_functions.OllamaEmbeddingFunction(
    url="http://localhost:11434/api/embeddings",
    model_name="nomic-embed-text"
)

collection_chroma = chroma_client.get_or_create_collection(
    name="contrats_juridiques",
    embedding_function=ollama_ef
)

text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50
)

# --- MODÈLES SQLALCHEMY ---
class UserSQL(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="Juriste")

class ContratSQL(Base):
    __tablename__ = "contrats"

    id = Column(Integer, primary_key=True, index=True)
    titre = Column(String, nullable=False)
    categorie = Column(String, default="Général")
    nom_fichier = Column(String, nullable=False)
    chemin_fichier = Column(String, nullable=False)
    texte_extrait = Column(Text, nullable=True)
    date_importation = Column(DateTime, default=datetime.utcnow)

class LogSQL(Base):
    __tablename__ = "logs"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, nullable=False)
    action = Column(String, nullable=False)
    details = Column(String, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

class ChatMessageSQL(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, index=True)
    user_email = Column(String, nullable=False)
    role = Column(String, nullable=False)  # 'user' ou 'assistant'
    content = Column(Text, nullable=False)
    sources_json = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)

Base.metadata.create_all(bind=engine)

def enregistrer_log(db: Session, email: str, action: str, details: str = None):
    log = LogSQL(user_email=email, action=action, details=details)
    db.add(log)
    db.commit()

# --- SCHÉMAS PYDANTIC ---
class UserCreate(BaseModel):
    email: EmailStr
    password: str
    role: str = "Juriste"

class RAGChatRequest(BaseModel):
    question: str
    contrat_id: int = None

# --- INITIALISATION ADMIN ---
@app.on_event("startup")
def startup_event():
    db = next(get_db())
    admin_exists = db.query(UserSQL).filter(UserSQL.role == "Administrateur").first()
    if not admin_exists:
        default_admin = UserSQL(
            email="admin@legal.com",
            hashed_password=hash_password("admin123"),
            role="Administrateur"
        )
        db.add(default_admin)
        db.commit()
        print("🟢 Compte Administrateur par défaut prêt : admin@legal.com / admin123")
    db.close()

# --- ROUTES AUTHENTIFICATION ET UTILISATEURS ---
@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    email_clean = form_data.username.strip().lower()
    db_user = db.query(UserSQL).filter(UserSQL.email == email_clean).first()
    
    if not db_user or not verify_password(form_data.password, db_user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Identifiants invalides")
    
    token = create_access_token(data={"sub": db_user.email, "role": db_user.role})
    enregistrer_log(db, db_user.email, "Connexion", "Utilisateur connecté avec succès")
    return {
        "access_token": token, 
        "token_type": "bearer",
        "role": db_user.role,
        "email": db_user.email
    }

@app.post("/register", status_code=status.HTTP_201_CREATED)
def register(
    new_user: UserCreate, 
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    if current_user["role"] != "Administrateur":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    
    db_user = db.query(UserSQL).filter(UserSQL.email == new_user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="E-mail déjà utilisé")
    
    user_to_create = UserSQL(
        email=new_user.email, 
        hashed_password=hash_password(new_user.password), 
        role=new_user.role
    )
    db.add(user_to_create)
    db.commit()
    enregistrer_log(db, current_user["email"], "Création Compte", f"Création du compte {new_user.email} ({new_user.role})")
    return {"message": f"Compte {user_to_create.role} créé avec succès", "email": user_to_create.email}

@app.get("/users")
def lister_utilisateurs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    if current_user["role"] != "Administrateur":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    
    users = db.query(UserSQL).all()
    return [{"id": u.id, "email": u.email, "role": u.role} for u in users]

@app.delete("/users/{user_id}")
def supprimer_utilisateur(
    user_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    if current_user["role"] != "Administrateur":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    
    user = db.query(UserSQL).filter(UserSQL.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur non trouvé")
    
    if user.email == current_user["email"]:
        raise HTTPException(status_code=400, detail="Vous ne pouvez pas supprimer votre propre compte")
    
    email_supprime = user.email
    db.delete(user)
    db.commit()
    enregistrer_log(db, current_user["email"], "Suppression Compte", f"Compte supprimé : {email_supprime}")
    return {"message": f"Utilisateur {email_supprime} supprimé avec succès"}

@app.get("/logs")
def lister_logs(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    if current_user["role"] != "Administrateur":
        raise HTTPException(status_code=403, detail="Réservé aux administrateurs")
    
    logs = db.query(LogSQL).order_by(LogSQL.timestamp.desc()).limit(100).all()
    return [
        {
            "id": l.id,
            "date": l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            "utilisateur": l.user_email,
            "action": l.action,
            "details": l.details
        }
        for l in logs
    ]

# --- MODULE CONTRATS & PARSING ---
def extraire_texte_pdf(chemin_fichier: str) -> str:
    texte = ""
    try:
        reader = pypdf.PdfReader(chemin_fichier)
        for page in reader.pages:
            t = page.extract_text()
            if t:
                texte += t + "\n"
    except Exception as e:
        print(f"Erreur d'extraction : {e}")
    return texte.strip()

@app.post("/contracts/upload", status_code=status.HTTP_201_CREATED)
async def importer_contrat(
    titre: str = Form(...),
    categorie: str = Form("Général"),
    fichier: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    if not fichier.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Seuls les fichiers PDF sont acceptés")
    
    chemin_destination = os.path.join(DOSSIER_STOCKAGE, fichier.filename)
    with open(chemin_destination, "wb") as buffer:
        contenu = await fichier.read()
        buffer.write(contenu)
    
    texte_extrait = extraire_texte_pdf(chemin_destination)
    
    nouveau_contrat = ContratSQL(
        titre=titre,
        categorie=categorie,
        nom_fichier=fichier.filename,
        chemin_fichier=chemin_destination,
        texte_extrait=texte_extrait
    )
    db.add(nouveau_contrat)
    db.commit()
    db.refresh(nouveau_contrat)
    
    chunks = []
    if texte_extrait:
        chunks = text_splitter.split_text(texte_extrait)
        ids = [f"contrat_{nouveau_contrat.id}_chunk_{i}" for i in range(len(chunks))]
        metadatas = [
            {"contrat_id": nouveau_contrat.id, "titre": nouveau_contrat.titre, "chunk_index": i} 
            for i in range(len(chunks))
        ]
        collection_chroma.add(documents=chunks, metadatas=metadatas, ids=ids)
    
    enregistrer_log(db, current_user["email"], "Importation Contrat", f"Contrat ajouté : {titre} ({fichier.filename})")
    
    return {
        "id": nouveau_contrat.id,
        "titre": nouveau_contrat.titre,
        "nom_fichier": nouveau_contrat.nom_fichier,
        "chunks_indexes": len(chunks),
        "apercu": texte_extrait[:200] + "..." if texte_extrait else "Aucun texte"
    }

@app.get("/contracts/")
def lister_contrats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    contrats = db.query(ContratSQL).all()
    return [
        {
            "id": c.id,
            "titre": c.titre,
            "categorie": c.categorie,
            "nom_fichier": c.nom_fichier,
            "date_importation": c.date_importation.strftime("%Y-%m-%d %H:%M")
        }
        for c in contrats
    ]

@app.put("/contracts/{contract_id}")
async def modifier_contrat(
    contract_id: int,
    titre: str = Form(...),
    categorie: str = Form("Général"),
    fichier: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    contrat = db.query(ContratSQL).filter(ContratSQL.id == contract_id).first()
    if not contrat:
        raise HTTPException(status_code=404, detail="Contrat non trouvé")
    
    contrat.titre = titre
    contrat.categorie = categorie
    
    if fichier and fichier.filename:
        chemin_destination = os.path.join(DOSSIER_STOCKAGE, fichier.filename)
        with open(chemin_destination, "wb") as buffer:
            contenu = await fichier.read()
            buffer.write(contenu)
        
        texte_extrait = extraire_texte_pdf(chemin_destination)
        contrat.nom_fichier = fichier.filename
        contrat.chemin_fichier = chemin_destination
        contrat.texte_extrait = texte_extrait
        
        try:
            collection_chroma.delete(where={"contrat_id": contract_id})
        except Exception as e:
            print(f"Erreur purge ChromaDB : {e}")
            
        if texte_extrait:
            chunks = text_splitter.split_text(texte_extrait)
            ids = [f"contrat_{contract_id}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [
                {"contrat_id": contract_id, "titre": titre, "chunk_index": i} 
                for i in range(len(chunks))
            ]
            collection_chroma.add(documents=chunks, metadatas=metadatas, ids=ids)
            
    db.commit()
    db.refresh(contrat)
    enregistrer_log(db, current_user["email"], "Modification Contrat", f"Contrat mis à jour (ID: {contract_id})")
    
    return {"message": "Contrat mis à jour avec succès", "id": contract_id}

@app.delete("/contracts/{contract_id}")
def supprimer_contrat(
    contract_id: int,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    contrat = db.query(ContratSQL).filter(ContratSQL.id == contract_id).first()
    if not contrat:
        raise HTTPException(status_code=404, detail="Contrat non trouvé")
    
    if os.path.exists(contrat.chemin_fichier):
        try:
            os.remove(contrat.chemin_fichier)
        except Exception as e:
            print(f"Erreur suppression fichier : {e}")
            
    try:
        collection_chroma.delete(where={"contrat_id": contract_id})
    except Exception as e:
        print(f"Erreur suppression ChromaDB : {e}")
        
    titre_supprime = contrat.titre
    db.delete(contrat)
    db.commit()
    
    enregistrer_log(db, current_user["email"], "Suppression Contrat", f"Contrat supprimé : {titre_supprime} (ID: {contract_id})")
    return {"message": f"Contrat '{titre_supprime}' supprimé avec succès"}

@app.post("/contracts/reindex")
def reindexer_tous_les_contrats(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    contrats = db.query(ContratSQL).all()
    compteur = 0
    for c in contrats:
        if c.texte_extrait:
            chunks = text_splitter.split_text(c.texte_extrait)
            ids = [f"contrat_{c.id}_chunk_{i}" for i in range(len(chunks))]
            metadatas = [{"contrat_id": c.id, "titre": c.titre, "chunk_index": i} for i in range(len(chunks))]
            collection_chroma.upsert(documents=chunks, metadatas=metadatas, ids=ids)
            compteur += 1
            
    enregistrer_log(db, current_user["email"], "Ré-indexation", f"{compteur} contrat(s) ré-indexé(s)")
    return {"message": f"{compteur} contrat(s) ré-indexé(s) avec succès dans ChromaDB !"}

# --- MODULE CHAT INTERACTIF & HISTORIQUE ---
@app.get("/rag/history")
def obtenir_historique_chat(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    messages = db.query(ChatMessageSQL).filter(ChatMessageSQL.user_email == current_user["email"]).order_by(ChatMessageSQL.timestamp.asc()).all()
    return [
        {
            "id": m.id,
            "role": m.role,
            "content": m.content,
            "sources": json.loads(m.sources_json) if m.sources_json else [],
            "timestamp": m.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        }
        for m in messages
    ]

@app.delete("/rag/history")
def effacer_historique_chat(
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    db.query(ChatMessageSQL).filter(ChatMessageSQL.user_email == current_user["email"]).delete()
    db.commit()
    enregistrer_log(db, current_user["email"], "Purge Historique", "Historique du chat effacé")
    return {"message": "Historique de conversation réinitialisé avec succès"}

@app.post("/rag/chat")
def chat_interactif(
    request: RAGChatRequest,
    db: Session = Depends(get_db),
    current_user: dict = Depends(get_current_user_data)
):
    # 1. Enregistrer le message utilisateur
    user_msg = ChatMessageSQL(
        user_email=current_user["email"],
        role="user",
        content=request.question
    )
    db.add(user_msg)
    db.commit()

    # 2. Recherche vectorielle dans ChromaDB
    where_filter = {"contrat_id": request.contrat_id} if request.contrat_id else None
    results = collection_chroma.query(
        query_texts=[request.question],
        n_results=5,
        where=where_filter
    )
    
    retrieved_docs = results.get("documents", [[]])[0]
    retrieved_meta = results.get("metadatas", [[]])[0]
    
    sources = [{"contrat": m.get("titre"), "extrait": d} for m, d in zip(retrieved_meta, retrieved_docs)] if retrieved_docs else []
    
    # 3. Récupérer les 6 derniers messages de contexte de la conversation
    historique_recent = db.query(ChatMessageSQL).filter(
        ChatMessageSQL.user_email == current_user["email"]
    ).order_by(ChatMessageSQL.timestamp.desc()).limit(6).all()
    
    historique_formate = ""
    for msg in reversed(historique_recent[:-1]):  # Exclure le tout dernier message qu'on vient d'ajouter
        historique_formate += f"{'Utilisateur' if msg.role == 'user' else 'Assistant'}: {msg.content}\n"

    contexte_docs = "\n\n---\n\n".join(retrieved_docs) if retrieved_docs else "Aucun document spécifique trouvé."

    if request.contrat_id:
        consigne_ia = "Ton objectif est de répondre EXCLUSIVEMENT en te basant sur les extraits du document ciblé ci-dessous. Ne croise pas avec d'autres affaires."
    else:
        consigne_ia = "Ton objectif est de faire une synthèse transversale en croisant les informations des différents documents juridiques fournis dans les extraits ci-dessous."

    prompt_complet = f"""Tu es un assistant juridique expert, courtois et précis. {consigne_ia}

HISTORIQUE DU CHAT :
{historique_formate}

EXTRAITS DE DOCUMENTS PERTINENTS :
{contexte_docs}

NOUVELLE QUESTION DE L'UTILISATEUR :
{request.question}

RÉPONSE DU JURISTE :"""

    try:
        ollama_res = requests.post(
            "http://localhost:11434/api/generate",
            json={
                "model": "llama3.2",
                "prompt": prompt_complet,
                "stream": False
            },
            timeout=300
        )
        if ollama_res.status_code == 200:
            reponse_ia = ollama_res.json().get("response", "Aucune réponse générée.")
        else:
            reponse_ia = "Erreur de communication avec le serveur Ollama."
    except Exception as e:
        reponse_ia = f"Erreur serveur Ollama : {e}"

    # 4. Enregistrer la réponse de l'assistant
    assistant_msg = ChatMessageSQL(
        user_email=current_user["email"],
        role="assistant",
        content=reponse_ia,
        sources_json=json.dumps(sources)
    )
    db.add(assistant_msg)
    db.commit()

    enregistrer_log(db, current_user["email"], "Interaction Chat", f"Question : {request.question[:40]}...")

    return {"reponse": reponse_ia, "sources": sources}