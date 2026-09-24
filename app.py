# app.py - Frontend Streamlit avec chat interactif et gestion d'historique en direct

import streamlit as st
import requests

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Plateforme Juridique", layout="wide", page_icon="⚖️")

if "token" not in st.session_state:
    st.session_state["token"] = None
if "role" not in st.session_state:
    st.session_state["role"] = None
if "email" not in st.session_state:
    st.session_state["email"] = None

def get_headers():
    token = st.session_state.get("token")
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}

# --- BARRE LATÉRALE ---
with st.sidebar:
    
    if not st.session_state["token"]:
        st.subheader("Connexion")
        email_input = st.text_input("Email").strip().lower()
        password_input = st.text_input("Mot de passe", type="password")
        
        if st.button("Se connecter", type="primary"):
            if email_input and password_input:
                payload = {"username": email_input, "password": password_input}
                res = requests.post(f"{API_URL}/login", data=payload)
                
                if res.status_code == 200:
                    data = res.json()
                    st.session_state["token"] = data.get("access_token")
                    st.session_state["role"] = data.get("role")
                    st.session_state["email"] = data.get("email")
                    st.success("Connexion réussie !")
                    st.rerun()
                else:
                    st.error(f"Échec : {res.json().get('detail', 'Identifiants incorrects')}")
            else:
                st.warning("Veuillez remplir tous les champs.")
    else:
        st.success(f"Connecté : **{st.session_state['email']}**")
        st.info(f"Rôle : **{st.session_state['role']}**")
        
        if st.button("Se déconnecter"):
            st.session_state["token"] = None
            st.session_state["role"] = None
            st.session_state["email"] = None
            st.rerun()

# --- PAGE PRINCIPALE ---
if not st.session_state["token"]:
    st.info("🔒 Veuillez vous connecter depuis la barre latérale pour accéder à la plateforme.")
else:
    st.title("⚖️ Workspace Juridique Intelligent")
    
    if st.session_state["role"] == "Administrateur":
        tab1, tab2, tab3, tab4 = st.tabs(["📤 Téléverser", "📁 Contrats", "💬 Assistant Chat", "⚙️ Administration"])
    else:
        tab1, tab2, tab3 = st.tabs(["📤 Téléverser", "📁 Contrats", "💬 Assistant Chat"])
        tab4 = None

    # TAB 1 : TÉLÉVERSEMENT
    with tab1:
        st.subheader("Importer un nouveau contrat (PDF)")
        titre = st.text_input("Titre du document", placeholder="ex: Contrat de prestation")
        categorie = st.selectbox("Catégorie", ["Général", "Bail", "Prestation de service", "Travail", "Plainte / Litige"])
        fichier_pdf = st.file_uploader("Choisir un fichier PDF", type=["pdf"])
        
        if st.button("Importer et Traiter", type="primary"):
            if titre and fichier_pdf:
                files = {"fichier": (fichier_pdf.name, fichier_pdf.getvalue(), "application/pdf")}
                data = {"titre": titre, "categorie": categorie}
                
                with st.spinner("Téléversement et indexation en cours..."):
                    res = requests.post(f"{API_URL}/contracts/upload", data=data, files=files, headers=get_headers())
                
                if res.status_code == 201:
                    info = res.json()
                    st.success(f"Document '{info['titre']}' importé et indexé !")
                    st.rerun()
                else:
                    st.error(f"Erreur : {res.json().get('detail')}")
            else:
                st.warning("Veuillez fournir un titre et un fichier PDF.")

    # TAB 2 : GESTION DES CONTRATS
    with tab2:
        st.subheader("Contrats enregistrés")
        
        col1, col2 = st.columns([1, 4])
        with col1:
            if st.button("🔄 Rafraîchir"):
                st.rerun()
        with col2:
            if st.button("⚡ Ré-indexer tous les documents"):
                with st.spinner("Ré-indexation en cours..."):
                    res_reindex = requests.post(f"{API_URL}/contracts/reindex", headers=get_headers())
                    if res_reindex.status_code == 200:
                        st.success(res_reindex.json().get("message"))

        res = requests.get(f"{API_URL}/contracts/", headers=get_headers())
        if res.status_code == 200:
            contrats = res.json()
            if contrats:
                st.dataframe(
                    contrats,
                    column_config={
                        "id": "ID",
                        "titre": "Titre du Document",
                        "categorie": "Catégorie",
                        "nom_fichier": "Nom Fichier",
                        "date_importation": "Date d'importation"
                    },
                    use_container_width=True,
                    hide_index=True
                )
                
                st.divider()
                st.markdown("### Actions sur un contrat")
                
                for c in contrats:
                    with st.expander(f"📄 ID {c['id']} - {c['titre']} ({c['categorie']})"):
                        c_act1, c_act2 = st.columns(2)
                        
                        # Modification
                        with c_act1:
                            with st.popover("✏️ Modifier ce contrat"):
                                st.write(f"**Modifier ID {c['id']}**")
                                edit_titre = st.text_input("Nouveau Titre", value=c['titre'], key=f"edit_t_{c['id']}")
                                edit_cat = st.selectbox(
                                    "Nouvelle Catégorie", 
                                    ["Général", "Bail", "Prestation de service", "Travail", "Plainte / Litige"],
                                    index=["Général", "Bail", "Prestation de service", "Travail", "Plainte / Litige"].index(c['categorie']) if c['categorie'] in ["Général", "Bail", "Prestation de service", "Travail", "Plainte / Litige"] else 0,
                                    key=f"edit_c_{c['id']}"
                                )
                                edit_file = st.file_uploader("Remplacer le PDF (facultatif)", type=["pdf"], key=f"edit_f_{c['id']}")
                                
                                if st.button("Valider les modifications", key=f"btn_edit_{c['id']}", type="primary"):
                                    data_mod = {"titre": edit_titre, "categorie": edit_cat}
                                    files_mod = None
                                    if edit_file:
                                        files_mod = {"fichier": (edit_file.name, edit_file.getvalue(), "application/pdf")}
                                    
                                    res_mod = requests.put(
                                        f"{API_URL}/contracts/{c['id']}", 
                                        data=data_mod, 
                                        files=files_mod, 
                                        headers=get_headers()
                                    )
                                    if res_mod.status_code == 200:
                                        st.success("Contrat mis à jour !")
                                        st.rerun()
                                    else:
                                        st.error("Échec de la modification.")
                        
                        # Suppression avec confirmation
                        with c_act2:
                            with st.popover("🗑️ Supprimer ce contrat"):
                                st.warning("⚠️ Voulez-vous vraiment supprimer définitivement ce document ?")
                                if st.button("Oui, confirmer la suppression", key=f"conf_del_c_{c['id']}", type="primary"):
                                    res_del = requests.delete(f"{API_URL}/contracts/{c['id']}", headers=get_headers())
                                    if res_del.status_code == 200:
                                        st.success("Document supprimé !")
                                        st.rerun()
                                    else:
                                        st.error("Erreur lors de la suppression.")
            else:
                st.info("Aucun document enregistré.")

    # TAB 3 : CHATBOT INTERACTIF (RAG CHAT)
    with tab3:
        st.subheader("💬 Chatbot Juridique")
        
        # Filtre optionnel sur un document
        res_contracts = requests.get(f"{API_URL}/contracts/", headers=get_headers())
        options_contrats = {"Tous les documents": None}
        if res_contracts.status_code == 200:
            for c in res_contracts.json():
                options_contrats[f"ID {c['id']} - {c['titre']}"] = c["id"]
        
        col_chat_head1, col_chat_head2 = st.columns([3, 1])
        with col_chat_head1:
            contrat_selectionne = st.selectbox("Cibler la recherche sur :", list(options_contrats.keys()))
            contrat_id = options_contrats[contrat_selectionne]
        with col_chat_head2:
            st.write("")
            st.write("")
            if st.button("🗑️ Effacer la discussion"):
                res_del_hist = requests.delete(f"{API_URL}/rag/history", headers=get_headers())
                if res_del_hist.status_code == 200:
                    st.success("Historique effacé !")
                    st.rerun()

        st.divider()

        # Récupération de l'historique depuis l'API
        res_hist = requests.get(f"{API_URL}/rag/history", headers=get_headers())
        historique = res_hist.json() if res_hist.status_code == 200 else []

        # Affichage du fil de discussion
        for msg in historique:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
                if msg["role"] == "assistant" and msg.get("sources"):
                    with st.expander("📜 Voir les sources documentaires"):
                        for idx, src in enumerate(msg["sources"], 1):
                            st.markdown(f"**Source {idx} ({src['contrat']}) :**")
                            st.caption(src["extrait"])

        # Zone d'envoi de nouveau message
        if prompt := st.chat_input("Posez votre question juridique ou demandez une synthèse..."):
            # Afficher immédiatement le message utilisateur
            with st.chat_message("user"):
                st.write(prompt)

            # Envoyer à l'API et traiter la réponse
            with st.chat_message("assistant"):
                with st.spinner("Analyse des documents et génération de la réponse..."):
                    payload = {"question": prompt, "contrat_id": contrat_id}
                    res_chat = requests.post(f"{API_URL}/rag/chat", json=payload, headers=get_headers())
                    
                    if res_chat.status_code == 200:
                        data = res_chat.json()
                        st.write(data["reponse"])
                        if data.get("sources"):
                            with st.expander("📜 Voir les sources documentaires"):
                                for idx, src in enumerate(data["sources"], 1):
                                    st.markdown(f"**Source {idx} ({src['contrat']}) :**")
                                    st.caption(src["extrait"])
                        st.rerun()
                    else:
                        st.error("Une erreur est survenue lors du traitement.")

    # TAB 4 : PANNEAU D'ADMINISTRATION
    if tab4:
        with tab4:
            st.subheader("⚙️ Administration de la plateforme")
            
            sub_tab1, sub_tab2, sub_tab3 = st.tabs(["➕ Créer Utilisateur", "👥 Gestion des Comptes", "📜 Journal d'Activité"])
            
            with sub_tab1:
                new_email = st.text_input("Email", key="admin_email").strip().lower()
                new_pass = st.text_input("Mot de passe", type="password", key="admin_pass")
                new_role = st.selectbox("Rôle", ["Juriste", "Administrateur"], key="admin_role")
                
                if st.button("Créer le compte", type="primary"):
                    if new_email and new_pass:
                        body = {"email": new_email, "password": new_pass, "role": new_role}
                        res = requests.post(f"{API_URL}/register", json=body, headers=get_headers())
                        if res.status_code in [200, 201]:
                            st.success(f"Compte créé pour {new_email} !")
                        else:
                            st.error(f"Erreur : {res.json().get('detail')}")

            with sub_tab2:
                st.write("### Liste des utilisateurs")
                res_users = requests.get(f"{API_URL}/users", headers=get_headers())
                if res_users.status_code == 200:
                    users_list = res_users.json()
                    
                    st.dataframe(
                        users_list,
                        column_config={"id": "ID", "email": "Adresse Email", "role": "Rôle"},
                        use_container_width=True,
                        hide_index=True
                    )
                    
                    st.divider()
                    st.write("### Supprimer un utilisateur")
                    for u in users_list:
                        if u['email'] != st.session_state["email"]:
                            col_u1, col_u2 = st.columns([3, 1])
                            col_u1.write(f"**{u['email']}** ({u['role']})")
                            with col_u2:
                                with st.popover(f"🗑️ Supprimer ID {u['id']}"):
                                    st.warning(f"Confirmer la suppression du compte {u['email']} ?")
                                    if st.button("Oui, supprimer", key=f"conf_del_u_{u['id']}", type="primary"):
                                        res_del_u = requests.delete(f"{API_URL}/users/{u['id']}", headers=get_headers())
                                        if res_del_u.status_code == 200:
                                            st.success("Utilisateur supprimé !")
                                            st.rerun()
                                        else:
                                            st.error("Erreur lors de la suppression.")

            with sub_tab3:
                st.write("### Activité récente sur la plateforme")
                if st.button("🔄 Actualiser le journal"):
                    st.rerun()
                
                res_logs = requests.get(f"{API_URL}/logs", headers=get_headers())
                if res_logs.status_code == 200:
                    st.dataframe(
                        res_logs.json(),
                        column_config={
                            "id": "ID",
                            "date": "Horodatage",
                            "utilisateur": "Utilisateur",
                            "action": "Action",
                            "details": "Détails"
                        },
                        use_container_width=True,
                        hide_index=True
                    )