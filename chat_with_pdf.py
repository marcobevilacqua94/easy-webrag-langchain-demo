import tempfile
from langchain_community.vectorstores import CouchbaseVectorStore
from langchain_openai import OpenAIEmbeddings
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
import os
import streamlit as st
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import RunnablePassthrough
from langchain_core.output_parsers import StrOutputParser

import asyncio

def get_or_create_eventloop():
    try:
        return asyncio.get_event_loop()
    except RuntimeError as ex:
        if "There is no current event loop in thread" in str(ex):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            return asyncio.get_event_loop()

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

def check_environment_variable(variable_name):
    """Check if environment variable is set"""
    if variable_name not in os.environ:
        st.error(
            f"{variable_name} environment variable is not set. Please add it to the _setup and secrets.toml file"
        )
        st.stop()


def save_to_vector_store(uploaded_file, vector_store):
    """Chunk the PDF & store it in Couchbase Vector Store"""
    if uploaded_file is not None:
        temp_dir = tempfile.TemporaryDirectory()
        temp_file_path = os.path.join(temp_dir.name, uploaded_file.name)

        with open(temp_file_path, "wb") as f:
            f.write(uploaded_file.getvalue())
            loader = PyPDFLoader(temp_file_path)
            docs = loader.load()

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=1500, chunk_overlap=150
        )

        doc_pages = text_splitter.split_documents(docs)

        vector_store.add_documents(doc_pages)
        st.info(f"PDF loaded into vector store in {len(doc_pages)} documents")


@st.cache_resource(show_spinner="Connecting to Vector Store")
def get_vector_store(
    _cluster,
    db_bucket,
    db_scope,
    db_collection,
    _embedding,
    index_name,
):
    """Return the Couchbase vector store"""
    vector_store = CouchbaseVectorStore(
        cluster=_cluster,
        bucket_name=db_bucket,
        scope_name=db_scope,
        collection_name=db_collection,
        embedding=_embedding,
        index_name=index_name,
    )
    return vector_store


@st.cache_resource(show_spinner="Connecting to Couchbase")
def connect_to_couchbase(connection_string, db_username, db_password):
    """Connect to couchbase"""
    from couchbase.cluster import Cluster
    from couchbase.auth import PasswordAuthenticator
    from couchbase.options import ClusterOptions
    from datetime import timedelta

    auth = PasswordAuthenticator(db_username, db_password)
    options = ClusterOptions(auth)
    connect_string = "couchbases://"+connection_string+"/?ssl=no_verify"
    cluster = Cluster(connect_string, options)

    # Wait until the cluster is ready for use.
    cluster.wait_until_ready(timedelta(seconds=5))

    return cluster


if __name__ == "__main__":
    # Authorization
    if "auth" not in st.session_state:
        st.session_state.auth = False

    st.set_page_config(
        page_title="Chat with your PDF using Langchain, Couchbase & Gemini",
        page_icon="ð¤",
        layout="centered",
        initial_sidebar_state="auto",
        menu_items=None,
    )

    AUTH = os.getenv("WEB_LOGIN_PASSWORD")
    check_environment_variable("WEB_LOGIN_PASSWORD")

    # Authentication
    user_pwd = st.text_input("Enter password", type="password")
    pwd_submit = st.button("Submit")

    if pwd_submit and user_pwd == AUTH:
        st.session_state.auth = True
    elif pwd_submit and user_pwd != AUTH:
        st.error("Incorrect password")

    if st.session_state.auth:
        # Load environment variables
        CB_HOSTNAME = os.getenv("CB_HOSTNAME")
        CB_USERNAME = os.getenv("CB_USERNAME")
        CB_PASSWORD = os.getenv("CB_PASSWORD")
        CB_BUCKET = os.getenv("CB_BUCKET")
        CB_SCOPE = os.getenv("CB_SCOPE")
        CB_COLLECTION = os.getenv("CB_COLLECTION")
        CB_SEARCHINDEX = os.getenv("CB_SEARCHINDEX")

        # Ensure that all environment variables are set
        check_environment_variable("OPENAI_API_KEY")
        check_environment_variable("GOOGLE_API_KEY")
        check_environment_variable("CB_HOSTNAME")
        check_environment_variable("CB_USERNAME")
        check_environment_variable("CB_PASSWORD")
        check_environment_variable("CB_BUCKET")
        check_environment_variable("CB_SCOPE")
        check_environment_variable("CB_COLLECTION")
        check_environment_variable("CB_SEARCHINDEX")

        # Use OpenAI Embeddings
       # embedding = OpenAIEmbeddings()
        embedding = GoogleGenerativeAIEmbeddings(model="models/embedding-001")

        # Connect to Couchbase Vector Store
        cluster = connect_to_couchbase(CB_HOSTNAME, CB_USERNAME, CB_PASSWORD)

        vector_store = get_vector_store(
            cluster,
            CB_BUCKET,
            CB_SCOPE,
            CB_COLLECTION,
            embedding,
            CB_SEARCHINDEX,
        )

        # Use couchbase vector store as a retriever for RAG
        retriever = vector_store.as_retriever()

        # Build the prompt for the RAG
        template = """You are a helpful bot. If you cannot answer based on the context provided, respond with a generic answer. Answer the question as truthfully as possible using the context below:
        {context}

        Question: {question}"""

        prompt = ChatPromptTemplate.from_template(template)

        # Use OpenAI GPT 4 as the LLM for the RAG
     #   llm = ChatOpenAI(temperature=0, model="gpt-4-1106-preview", streaming=True)
        llm = ChatGoogleGenerativeAI(model="gemini-pro")
        # RAG chain
        chain = (
            {"context": retriever, "question": RunnablePassthrough()}
            | prompt
            | llm
            | StrOutputParser()
        )

        # Pure OpenAI output without RAG
        template_without_rag = """You are a helpful bot. Answer the question as truthfully as possible.

        Question: {question}"""

        prompt_without_rag = ChatPromptTemplate.from_template(template_without_rag)

     #   llm_without_rag = ChatOpenAI(model="gpt-4-1106-preview")
        llm_without_rag = ChatGoogleGenerativeAI(model="gemini-pro")
        chain_without_rag = (
            {"question": RunnablePassthrough()}
            | prompt_without_rag
            | llm_without_rag
            | StrOutputParser()
        )

        # Frontend
        couchbase_logo = (
            "https://emoji.slack-edge.com/T024FJS4M/couchbase/4a361e948b15ed91.png"
        )
        openai_logo = (
            "https://uxwing.com/wp-content/themes/uxwing/download/brands-and-social-media/google-gemini-icon.png"
        )

        st.title("Chat with PDF")
        st.markdown(
            "Answers with [Couchbase logo](https://emoji.slack-edge.com/T024FJS4M/couchbase/4a361e948b15ed91.png) are generated using *RAG* while [Gemini logo](https://uxwing.com/wp-content/themes/uxwing/download/brands-and-social-media/google-gemini-icon.png) are generated by pure *LLM (Gemini)*"
        )

        with st.sidebar:
            st.header("Upload your PDF")
            with st.form("upload pdf"):
                uploaded_file = st.file_uploader(
                    "Choose a PDF.",
                    help="The document will be deleted after one hour of inactivity (TTL).",
                    type="pdf",
                )
                submitted = st.form_submit_button("Upload & Vectorize")
                if submitted:
                    # store the PDF in the vector store after chunking
                    save_to_vector_store(uploaded_file, vector_store)

            st.subheader("How does it work?")
            st.markdown(
                """
                For each question, you will get two answers:
                * one using RAG ([Couchbase logo](https://emoji.slack-edge.com/T024FJS4M/couchbase/4a361e948b15ed91.png))
                * one using pure LLM - Gemini ([Gemini logo](https://uxwing.com/wp-content/themes/uxwing/download/brands-and-social-media/google-gemini-icon.png)).
                """
            )

            st.markdown(
                "For RAG, we are using [Langchain](https://langchain.com/), [Couchbase Vector Search](https://couchbase.com/) & [OpenAI](https://openai.com/). We fetch parts of the PDF relevant to the question using Vector search & add it as the context to the LLM. The LLM is instructed to answer based on the context from the Vector Store."
            )

            # View Code
            if st.checkbox("View Code"):
                st.write(
                    "View the code here: [Github](https://github.com/jon-strabala/easy-webrag-langchain-demo/blob/main/chat_with_pdf.py)"
                )

        if "messages" not in st.session_state:
            st.session_state.messages = []
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": "Hi, I'm a chatbot who can chat with the PDF. How can I help you?",
                    "avatar": openai_logo,
                }
            )

        # Display chat messages from history on app rerun
        for message in st.session_state.messages:
            with st.chat_message(message["role"], avatar=message["avatar"]):
                st.markdown(message["content"])

        # React to user input
        if question := st.chat_input("Ask a question based on the PDF(s)"):
            # Reset show_rag_context to False on new question
            st.session_state.show_rag_context = False

            # Display user message in chat message container
            st.chat_message("user").markdown(question)

            # Add user message to chat history
            st.session_state.messages.append(
                {"role": "user", "content": question, "avatar": openai_logo}
            )

            # Stream the response from the pure LLM
            with st.chat_message("assistant", avatar=openai_logo):
                message_placeholder_pure_llm = st.empty()

            pure_llm_response = ""
            for chunk in chain_without_rag.stream(question):
                pure_llm_response += chunk
                message_placeholder_pure_llm.markdown(pure_llm_response + "â")

            message_placeholder_pure_llm.markdown(pure_llm_response)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": pure_llm_response,
                    "avatar": openai_logo,
                }
            )

            # Capture context and question for display
            rag_context = {"context": retriever.get_relevant_documents(question), "question": question}

            # Save context in session state
            st.session_state.rag_context = str(rag_context)

            # Show the button after pure LLM response
            st.session_state.show_rag_button = True

            # Stream the response from the RAG
            with st.chat_message("assistant", avatar=couchbase_logo):
                message_placeholder = st.empty()

            rag_response = ""
            for chunk in chain.stream(question):
                rag_response += chunk
                message_placeholder.markdown(rag_response + "â")

            message_placeholder.markdown(rag_response)
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": rag_response,
                    "avatar": couchbase_logo,
                }
            )
