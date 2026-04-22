import streamlit as st
import os
import json
import time
from google.cloud import storage

# --- CONFIGURAZIONE CORE ---
# Nota: su Streamlit Cloud useremo st.secrets invece del file fisico
BUCKET_NAME = "cad-vault-marco"

st.set_page_config(page_title="PORTALE CAD", layout="wide", page_icon="🏗️")

# --- FUNZIONE DI SICUREZZA ---
def check_password():
    """Restituisce True se l'utente ha inserito la password corretta tramite Secrets."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 Accesso Riservato")
        pwd = st.text_input("Inserisci la password dell'Archivio", type="password")
        if st.button("Accedi"):
            # Verifica la password dai Secrets di Streamlit Cloud
            try:
                if pwd == st.secrets["login"]["password"]:
                    st.session_state["password_correct"] = True
                    st.rerun()
                else:
                    st.error("Password errata")
            except KeyError:
                st.error("Errore di configurazione: 'login/password' non trovato nei Secrets.")
        return False
    return True

# --- CSS AD ALTO CONTRASTO (Leggibilità Estrema - B&W) ---
st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Arial:wght@400;700&display=swap');
    
    .stApp { background-color: #ffffff; color: #000000; font-family: 'Arial', sans-serif !important; }
    h1, h2, h3, h4, label, p, .stMarkdown { color: #000000 !important; }
    
    .stButton>button { 
        background-color: #000000; color: #ffffff !important; 
        font-weight: bold; border-radius: 0px; border: 2px solid #000000;
        width: 100%; height: 50px; transition: all 0.1s;
    }
    .stButton>button:hover { background-color: #333333; color: #ffffff !important; }

    .stTextInput>div>div>input, .stTextArea>div>div>textarea, .stSelectbox>div>div>div { 
        border: 2px solid #000000 !important; color: #000000 !important; 
        border-radius: 0px !important; background-color: #ffffff !important;
    }
    
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { 
        height: 50px; background-color: #eeeeee; border: 1px solid #000000; color: #000000;
    }
    .stTabs [aria-selected="true"] { background-color: #000000 !important; color: #ffffff !important; }
    
    .stWarning, .stInfo, .stSuccess { 
        background-color: #f8f9fa !important; border: 1px solid #000000 !important; color: #000000 !important; 
    }
    </style>
    """, unsafe_allow_html=True)

# --- LOGICA APPLICATIVO ---
if check_password():
    # Inizializzazione Google Cloud dai Secrets (Richiesto per Cloud Deployment)
    try:
        gcp_info = json.loads(st.secrets["gcp_service_account"])
        client = storage.Client.from_service_account_info(gcp_info)
        bucket = client.bucket(BUCKET_NAME)
    except Exception as e:
        st.error(f"Errore di connessione a Google Cloud: {e}")
        st.stop()

    # RECUPERO CATEGORIE DINAMICHE
    try:
        cats_json = bucket.blob("metadata/categories.json").download_as_text()
        lista_categorie = json.loads(cats_json)
    except:
        lista_categorie = ["Definizione categorie in corso..."]

    tab1, tab2 = st.tabs(["🚀 CHECK-IN", "🔍 CHECK-OUT"])

    # --- TAB 1: CHECK-IN ---
    with tab1:
        st.subheader("Inserimento Nuovo Articolo")
        st.markdown("⚠️ **ATTENZIONE**: Carica solo i file relativi a **UN SINGOLO CODICE** (es. .stp + .pdf + .dwg).")
        
        with st.form("form_checkin", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                nome_articolo = st.text_input("NOME ARTICOLO (sarà il nome finale dei file e della cartella)")
                categoria = st.selectbox("DESTINAZIONE (Sottocategoria)", lista_categorie)
            with col2:
                tags = st.text_input("TAG (separati da virgola)")
                solo_trasferimento = st.checkbox("SOLO TRASFERIMENTO (Nessuna rinomina automatica)")

            note = st.text_area("NOTE TECNICHE")
            upload_files = st.file_uploader("Trascina i file dell'articolo", accept_multiple_files=True)
            
            st.write("---")
            if st.form_submit_button("INVIA ALL'AGENTE"):
                if upload_files and nome_articolo:
                    with st.spinner("INVIO IN CORSO..."):
                        # Creazione pacchetto metadati
                        task_data = {
                            "nome_articolo": nome_articolo,
                            "categoria": categoria,
                            "tags": [t.strip() for t in tags.split(",")] if tags else [],
                            "note": note,
                            "solo_trasferimento": solo_trasferimento,
                            "timestamp": time.time()
                        }
                        
                        # 1. Upload Task JSON
                        bucket.blob(f"inbox/{nome_articolo}.json").upload_from_string(json.dumps(task_data, indent=4))
                        
                        # 2. Upload Files in subfolder
                        for f in upload_files:
                            bucket.blob(f"inbox/{nome_articolo}/{f.name}").upload_from_file(f)
                            
                        st.balloons()
                        st.success(f"✅ Articolo {nome_articolo} inviato correttamente!")
                else:
                    st.error("ERRORE: Inserire Nome Articolo e almeno un file.")

    # --- TAB 2: CHECK-OUT ---
    with tab2:
        st.subheader("Ricerca nell'Indice Centrale")
        
        # Lettura archivio.json dal Cloud
        try:
            idx_blob = bucket.blob("metadata/archivio_index.json").download_as_text()
            index_data = json.loads(idx_blob)["components"]
        except:
            st.error("Indice non disponibile. Avvia il Bridge sul PC H24.")
            index_data = []

        # GRIGLIA DI RICERCA (Logica AND)
        c1, c2 = st.columns(2)
        with c1: n1 = st.text_input("Parola Nome 1").lower()
        with c2: n2 = st.text_input("Parola Nome 2").lower()
        
        t1, t2, t3 = st.columns(3)
        with t1: tag1 = st.text_input("Tag 1").lower()
        with t2: tag2 = st.text_input("Tag 2").lower()
        with t3: tag3 = st.text_input("Tag 3").lower()

        if index_data:
            results = []
            for item in index_data:
                code = item.get('code', '').lower()
                tags_list = " ".join(item.get('tags', [])).lower()
                if (n1 in code and n2 in code) and (tag1 in tags_list and tag2 in tags_list and tag3 in tags_list):
                    results.append(item)

            st.markdown(f"### Risultati trovati: **{len(results)}**")
            
            selected_codes = []
            for res in results:
                if st.checkbox(f"📦 {res['code']} | {res['category']}", key=f"out_{res['code']}"):
                    selected_codes.append(res['code'])

            st.write("---")
            if st.button("PREPARA LINK DI DOWNLOAD"):
                if selected_codes:
                    req_id = int(time.time())
                    req = {"items": selected_codes, "request_id": req_id, "timestamp": time.time()}
                    bucket.blob(f"requests/req_{req_id}.json").upload_from_string(json.dumps(req, indent=4))
                    st.session_state['last_req_id'] = req_id
                    st.success(f"⌛ Richiesta **req_{req_id}** inviata. Il Bridge sta zippando i file.")
                else:
                    st.error("Selezionare almeno un elemento!")
            
            # --- LOGICA DI RECUPERO LINK ---
            if 'last_req_id' in st.session_state:
                req_id = st.session_state['last_req_id']
                res_blob = bucket.blob(f"responses/{req_id}.json")
                if res_blob.exists():
                    res_data = json.loads(res_blob.download_as_text())
                    st.markdown("---")
                    st.markdown(f"### ✅ IL TUO DOWNLOAD È PRONTO!")
                    st.link_button("CLICCA QUI PER SCARICARE LO ZIP", res_data['url'])
                else:
                    st.write("Stato: In elaborazione... clicca 'Aggiorna' tra poco.")
                    if st.button("AGGIORNA STATO DOWNLOAD"):
                        st.rerun()
