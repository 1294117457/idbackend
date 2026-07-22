--
-- PostgreSQL database dump
--

\restrict rRDFCyqDpGBgrdEdfNqYov1aXbhVRKfwrg7gypficpJvANpU1bjGFEFOdv8rw5g

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 17.6

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: public; Type: SCHEMA; Schema: -; Owner: pg_database_owner
--

CREATE SCHEMA public;


ALTER SCHEMA public OWNER TO pg_database_owner;

--
-- Name: SCHEMA public; Type: COMMENT; Schema: -; Owner: pg_database_owner
--

COMMENT ON SCHEMA public IS 'standard public schema';


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: agent_sessions; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.agent_sessions (
    user_id integer NOT NULL,
    session_id character varying(100) NOT NULL,
    session_metadata json,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.agent_sessions OWNER TO zhouch;

--
-- Name: agent_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.agent_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.agent_sessions_id_seq OWNER TO zhouch;

--
-- Name: agent_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.agent_sessions_id_seq OWNED BY public.agent_sessions.id;


--
-- Name: application_operation; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.application_operation (
    application_id integer NOT NULL,
    operator_id integer NOT NULL,
    operator_name character varying(100) NOT NULL,
    operation character varying(20) NOT NULL,
    remark text,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.application_operation OWNER TO zhouch;

--
-- Name: application_operation_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.application_operation_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.application_operation_id_seq OWNER TO zhouch;

--
-- Name: application_operation_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.application_operation_id_seq OWNED BY public.application_operation.id;


--
-- Name: application_proofs; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.application_proofs (
    application_id integer NOT NULL,
    file_id integer,
    proof_score numeric(5,2) NOT NULL,
    status character varying(20) NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    is_adjusted boolean DEFAULT false NOT NULL
);


ALTER TABLE public.application_proofs OWNER TO zhouch;

--
-- Name: COLUMN application_proofs.is_adjusted; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.application_proofs.is_adjusted IS '是否被老师修正过：false=学生申报分，true=老师修正过的分';


--
-- Name: application_proofs_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.application_proofs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.application_proofs_id_seq OWNER TO zhouch;

--
-- Name: application_proofs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.application_proofs_id_seq OWNED BY public.application_proofs.id;


--
-- Name: applications; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.applications (
    user_id integer NOT NULL,
    template_id integer NOT NULL,
    template_name character varying(100) NOT NULL,
    category_id integer,
    apply_score numeric(5,2) NOT NULL,
    gain_score numeric(5,2) NOT NULL,
    status character varying(20) NOT NULL,
    review_count integer NOT NULL,
    approved_count integer NOT NULL,
    rejected_count integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    reviewer_ids jsonb DEFAULT '[]'::jsonb NOT NULL
);


ALTER TABLE public.applications OWNER TO zhouch;

--
-- Name: applications_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.applications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.applications_id_seq OWNER TO zhouch;

--
-- Name: applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.applications_id_seq OWNED BY public.applications.id;


--
-- Name: attribute; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.attribute (
    name character varying(100) NOT NULL,
    group_code character varying(50) NOT NULL,
    group_name character varying(100) NOT NULL,
    type character varying(20) NOT NULL,
    value text NOT NULL,
    input_min numeric(10,4),
    input_max numeric(10,4),
    sort_order integer NOT NULL,
    description text,
    is_active boolean NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_attribute_type_enum CHECK (((type)::text = ANY (ARRAY[('CONDITION'::character varying)::text, ('TRANSFORM'::character varying)::text])))
);


ALTER TABLE public.attribute OWNER TO zhouch;

--
-- Name: attribute_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.attribute_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.attribute_id_seq OWNER TO zhouch;

--
-- Name: attribute_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.attribute_id_seq OWNED BY public.attribute.id;


--
-- Name: embeddings; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.embeddings (
    id integer NOT NULL,
    title character varying(200),
    content text NOT NULL,
    category character varying(50) NOT NULL,
    ref_id integer,
    embedding public.vector(1024),
    created_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp with time zone DEFAULT CURRENT_TIMESTAMP,
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple'::regconfig, (((COALESCE(title, ''::character varying))::text || ' '::text) || COALESCE(content, ''::text)))) STORED
);


ALTER TABLE public.embeddings OWNER TO zhouch;

--
-- Name: TABLE embeddings; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON TABLE public.embeddings IS '统一向量表，用于 RAG 检索';


--
-- Name: COLUMN embeddings.title; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.embeddings.title IS '标题（方便人类识别）';


--
-- Name: COLUMN embeddings.content; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.embeddings.content IS '内容原文（检索后展示用）';


--
-- Name: COLUMN embeddings.category; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.embeddings.category IS '业务类型：POLICY / SYSTEM_GUIDE / TEMPLATE';


--
-- Name: COLUMN embeddings.ref_id; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.embeddings.ref_id IS '关联业务 ID（如 template.id）';


--
-- Name: COLUMN embeddings.embedding; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.embeddings.embedding IS '1024 维 embedding 向量（JSON 数组存储）';


--
-- Name: embeddings_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.embeddings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.embeddings_id_seq OWNER TO zhouch;

--
-- Name: embeddings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.embeddings_id_seq OWNED BY public.embeddings.id;


--
-- Name: extra_info_field; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.extra_info_field (
    name character varying(128) NOT NULL,
    type character varying(20) NOT NULL,
    options json NOT NULL,
    is_active boolean NOT NULL,
    sort_order integer NOT NULL,
    description character varying(255),
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.extra_info_field OWNER TO zhouch;

--
-- Name: extra_info_field_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.extra_info_field_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.extra_info_field_id_seq OWNER TO zhouch;

--
-- Name: extra_info_field_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.extra_info_field_id_seq OWNED BY public.extra_info_field.id;


--
-- Name: file_metadata; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.file_metadata (
    object_name character varying(255) NOT NULL,
    original_name character varying(255) NOT NULL,
    file_size integer NOT NULL,
    content_type character varying(100),
    file_extension character varying(10),
    file_category character varying(20) NOT NULL,
    upload_user_id integer NOT NULL,
    is_deleted boolean NOT NULL,
    delete_time character varying(50),
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.file_metadata OWNER TO zhouch;

--
-- Name: COLUMN file_metadata.object_name; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.file_metadata.object_name IS 'S3 对象 key，如 files/proofs/2025/123/abc.pdf';


--
-- Name: COLUMN file_metadata.file_category; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.file_metadata.file_category IS '决定鉴权分支和 S3 路径前缀';


--
-- Name: COLUMN file_metadata.upload_user_id; Type: COMMENT; Schema: public; Owner: zhouch
--

COMMENT ON COLUMN public.file_metadata.upload_user_id IS '上传用户，部分鉴权场景使用';


--
-- Name: file_metadata_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.file_metadata_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.file_metadata_id_seq OWNER TO zhouch;

--
-- Name: file_metadata_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.file_metadata_id_seq OWNED BY public.file_metadata.id;


--
-- Name: permission; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.permission (
    permission_code character varying(100) NOT NULL,
    permission_name character varying(100) NOT NULL,
    api_path character varying(255),
    description character varying(255),
    sort_order integer NOT NULL,
    status boolean NOT NULL,
    group_code character varying(50) NOT NULL,
    group_name character varying(100) NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.permission OWNER TO zhouch;

--
-- Name: permission_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.permission_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.permission_id_seq OWNER TO zhouch;

--
-- Name: permission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.permission_id_seq OWNED BY public.permission.id;


--
-- Name: role; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.role (
    role_code character varying(50) NOT NULL,
    role_name character varying(100) NOT NULL,
    description character varying(255),
    sort_order integer NOT NULL,
    status boolean NOT NULL,
    is_system boolean NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.role OWNER TO zhouch;

--
-- Name: role_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.role_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.role_id_seq OWNER TO zhouch;

--
-- Name: role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.role_id_seq OWNED BY public.role.id;


--
-- Name: role_permission; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.role_permission (
    role_id integer NOT NULL,
    permission_id integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.role_permission OWNER TO zhouch;

--
-- Name: role_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.role_permission_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.role_permission_id_seq OWNER TO zhouch;

--
-- Name: role_permission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.role_permission_id_seq OWNED BY public.role_permission.id;


--
-- Name: rule; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.rule (
    type character varying(20) NOT NULL,
    score numeric(5,2),
    name character varying(100) NOT NULL,
    sort_order integer NOT NULL,
    description text,
    is_active boolean NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_rule_type_enum CHECK (((type)::text = ANY (ARRAY[('CONDITION'::character varying)::text, ('TRANSFORM'::character varying)::text])))
);


ALTER TABLE public.rule OWNER TO zhouch;

--
-- Name: rule_attribute; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.rule_attribute (
    rule_id integer NOT NULL,
    attribute_id integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.rule_attribute OWNER TO zhouch;

--
-- Name: rule_attribute_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.rule_attribute_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rule_attribute_id_seq OWNER TO zhouch;

--
-- Name: rule_attribute_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.rule_attribute_id_seq OWNED BY public.rule_attribute.id;


--
-- Name: rule_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.rule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rule_id_seq OWNER TO zhouch;

--
-- Name: rule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.rule_id_seq OWNED BY public.rule.id;


--
-- Name: score_data; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.score_data (
    user_id integer NOT NULL,
    application_id integer NOT NULL,
    category_id integer NOT NULL,
    name character varying(100),
    score numeric(5,2) NOT NULL,
    is_active boolean NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.score_data OWNER TO zhouch;

--
-- Name: score_data_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.score_data_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.score_data_id_seq OWNER TO zhouch;

--
-- Name: score_data_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.score_data_id_seq OWNED BY public.score_data.id;


--
-- Name: system_config; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.system_config (
    config_key character varying(100) NOT NULL,
    config_value character varying(500) NOT NULL,
    description character varying(200),
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.system_config OWNER TO zhouch;

--
-- Name: system_config_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.system_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.system_config_id_seq OWNER TO zhouch;

--
-- Name: system_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.system_config_id_seq OWNED BY public.system_config.id;


--
-- Name: template; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.template (
    name character varying(100) NOT NULL,
    category_id integer NOT NULL,
    max_score numeric(5,2) NOT NULL,
    review_count integer NOT NULL,
    sort_order integer NOT NULL,
    description text,
    is_active boolean NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    is_repeated boolean DEFAULT true NOT NULL,
    CONSTRAINT ck_template_max_score_nonneg CHECK ((max_score >= (0)::numeric))
);


ALTER TABLE public.template OWNER TO zhouch;

--
-- Name: template_category; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.template_category (
    name character varying(100) NOT NULL,
    parent_id integer,
    max_score numeric(5,2) NOT NULL,
    is_bind_template boolean NOT NULL,
    sort_order integer NOT NULL,
    is_active boolean NOT NULL,
    is_deleted boolean NOT NULL,
    description character varying(255),
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    CONSTRAINT ck_template_category_max_score_nonneg CHECK ((max_score >= (0)::numeric))
);


ALTER TABLE public.template_category OWNER TO zhouch;

--
-- Name: template_category_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.template_category_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.template_category_id_seq OWNER TO zhouch;

--
-- Name: template_category_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.template_category_id_seq OWNED BY public.template_category.id;


--
-- Name: template_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.template_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.template_id_seq OWNER TO zhouch;

--
-- Name: template_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.template_id_seq OWNED BY public.template.id;


--
-- Name: template_rule; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.template_rule (
    template_id integer NOT NULL,
    rule_id integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.template_rule OWNER TO zhouch;

--
-- Name: template_rule_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.template_rule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.template_rule_id_seq OWNER TO zhouch;

--
-- Name: template_rule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.template_rule_id_seq OWNED BY public.template_rule.id;


--
-- Name: user_role; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.user_role (
    user_id integer NOT NULL,
    role_id integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.user_role OWNER TO zhouch;

--
-- Name: user_role_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.user_role_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_role_id_seq OWNER TO zhouch;

--
-- Name: user_role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.user_role_id_seq OWNED BY public.user_role.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: zhouch
--

CREATE TABLE public.users (
    username character varying(255) NOT NULL,
    password character varying(255) NOT NULL,
    phone character varying(15),
    avatar character varying(500),
    status character varying(20) NOT NULL,
    last_login_at character varying(50),
    full_name character varying(100),
    grade integer,
    graduation_year integer,
    enrollment_year integer,
    major character varying(100),
    score_info json,
    extra_info json,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.users OWNER TO zhouch;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: zhouch
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO zhouch;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: zhouch
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: agent_sessions id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.agent_sessions ALTER COLUMN id SET DEFAULT nextval('public.agent_sessions_id_seq'::regclass);


--
-- Name: application_operation id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.application_operation ALTER COLUMN id SET DEFAULT nextval('public.application_operation_id_seq'::regclass);


--
-- Name: application_proofs id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.application_proofs ALTER COLUMN id SET DEFAULT nextval('public.application_proofs_id_seq'::regclass);


--
-- Name: applications id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.applications ALTER COLUMN id SET DEFAULT nextval('public.applications_id_seq'::regclass);


--
-- Name: attribute id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.attribute ALTER COLUMN id SET DEFAULT nextval('public.attribute_id_seq'::regclass);


--
-- Name: embeddings id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.embeddings ALTER COLUMN id SET DEFAULT nextval('public.embeddings_id_seq'::regclass);


--
-- Name: extra_info_field id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.extra_info_field ALTER COLUMN id SET DEFAULT nextval('public.extra_info_field_id_seq'::regclass);


--
-- Name: file_metadata id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.file_metadata ALTER COLUMN id SET DEFAULT nextval('public.file_metadata_id_seq'::regclass);


--
-- Name: permission id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.permission ALTER COLUMN id SET DEFAULT nextval('public.permission_id_seq'::regclass);


--
-- Name: role id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.role ALTER COLUMN id SET DEFAULT nextval('public.role_id_seq'::regclass);


--
-- Name: role_permission id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.role_permission ALTER COLUMN id SET DEFAULT nextval('public.role_permission_id_seq'::regclass);


--
-- Name: rule id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.rule ALTER COLUMN id SET DEFAULT nextval('public.rule_id_seq'::regclass);


--
-- Name: rule_attribute id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.rule_attribute ALTER COLUMN id SET DEFAULT nextval('public.rule_attribute_id_seq'::regclass);


--
-- Name: score_data id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.score_data ALTER COLUMN id SET DEFAULT nextval('public.score_data_id_seq'::regclass);


--
-- Name: system_config id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.system_config ALTER COLUMN id SET DEFAULT nextval('public.system_config_id_seq'::regclass);


--
-- Name: template id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template ALTER COLUMN id SET DEFAULT nextval('public.template_id_seq'::regclass);


--
-- Name: template_category id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template_category ALTER COLUMN id SET DEFAULT nextval('public.template_category_id_seq'::regclass);


--
-- Name: template_rule id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template_rule ALTER COLUMN id SET DEFAULT nextval('public.template_rule_id_seq'::regclass);


--
-- Name: user_role id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.user_role ALTER COLUMN id SET DEFAULT nextval('public.user_role_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: agent_sessions agent_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_pkey PRIMARY KEY (id);


--
-- Name: agent_sessions agent_sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_session_id_key UNIQUE (session_id);


--
-- Name: application_operation application_operation_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.application_operation
    ADD CONSTRAINT application_operation_pkey PRIMARY KEY (id);


--
-- Name: application_proofs application_proofs_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.application_proofs
    ADD CONSTRAINT application_proofs_pkey PRIMARY KEY (id);


--
-- Name: applications applications_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_pkey PRIMARY KEY (id);


--
-- Name: attribute attribute_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.attribute
    ADD CONSTRAINT attribute_pkey PRIMARY KEY (id);


--
-- Name: embeddings embeddings_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.embeddings
    ADD CONSTRAINT embeddings_pkey PRIMARY KEY (id);


--
-- Name: extra_info_field extra_info_field_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.extra_info_field
    ADD CONSTRAINT extra_info_field_pkey PRIMARY KEY (id);


--
-- Name: file_metadata file_metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.file_metadata
    ADD CONSTRAINT file_metadata_pkey PRIMARY KEY (id);


--
-- Name: permission permission_permission_code_key; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.permission
    ADD CONSTRAINT permission_permission_code_key UNIQUE (permission_code);


--
-- Name: permission permission_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.permission
    ADD CONSTRAINT permission_pkey PRIMARY KEY (id);


--
-- Name: role_permission role_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_pkey PRIMARY KEY (id);


--
-- Name: role role_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_pkey PRIMARY KEY (id);


--
-- Name: role role_role_code_key; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_role_code_key UNIQUE (role_code);


--
-- Name: rule_attribute rule_attribute_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.rule_attribute
    ADD CONSTRAINT rule_attribute_pkey PRIMARY KEY (id);


--
-- Name: rule rule_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.rule
    ADD CONSTRAINT rule_pkey PRIMARY KEY (id);


--
-- Name: score_data score_data_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.score_data
    ADD CONSTRAINT score_data_pkey PRIMARY KEY (id);


--
-- Name: system_config system_config_config_key_key; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_config_key_key UNIQUE (config_key);


--
-- Name: system_config system_config_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_pkey PRIMARY KEY (id);


--
-- Name: template_category template_category_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template_category
    ADD CONSTRAINT template_category_pkey PRIMARY KEY (id);


--
-- Name: template template_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_pkey PRIMARY KEY (id);


--
-- Name: template_rule template_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template_rule
    ADD CONSTRAINT template_rule_pkey PRIMARY KEY (id);


--
-- Name: rule_attribute uk_rule_attribute; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.rule_attribute
    ADD CONSTRAINT uk_rule_attribute UNIQUE (rule_id, attribute_id);


--
-- Name: template_rule uk_template_rule; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template_rule
    ADD CONSTRAINT uk_template_rule UNIQUE (template_id, rule_id);


--
-- Name: user_role user_role_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_pkey PRIMARY KEY (id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: idx_application_category; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_application_category ON public.applications USING btree (category_id);


--
-- Name: idx_application_status; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_application_status ON public.applications USING btree (status);


--
-- Name: idx_application_user_status; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_application_user_status ON public.applications USING btree (user_id, status);


--
-- Name: idx_applications_reviewer_ids_gin; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_applications_reviewer_ids_gin ON public.applications USING gin (reviewer_ids jsonb_path_ops);


--
-- Name: idx_attribute_active; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_attribute_active ON public.attribute USING btree (is_active);


--
-- Name: idx_attribute_group; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_attribute_group ON public.attribute USING btree (group_code);


--
-- Name: idx_embeddings_content_tsv; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_embeddings_content_tsv ON public.embeddings USING gin (content_tsv);


--
-- Name: idx_embeddings_hnsw; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_embeddings_hnsw ON public.embeddings USING hnsw (embedding public.vector_cosine_ops);


--
-- Name: idx_extra_info_field_active; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_extra_info_field_active ON public.extra_info_field USING btree (is_active);


--
-- Name: idx_extra_info_field_sort; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_extra_info_field_sort ON public.extra_info_field USING btree (sort_order, id);


--
-- Name: idx_operation_app_status; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_operation_app_status ON public.application_operation USING btree (application_id, operation);


--
-- Name: idx_operation_application; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_operation_application ON public.application_operation USING btree (application_id);


--
-- Name: idx_operation_operator; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_operation_operator ON public.application_operation USING btree (operator_id);


--
-- Name: idx_proofs_application; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_proofs_application ON public.application_proofs USING btree (application_id);


--
-- Name: idx_proofs_application_status; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_proofs_application_status ON public.application_proofs USING btree (application_id, status);


--
-- Name: idx_reviewers; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_reviewers ON public.applications USING gin (reviewer_ids jsonb_path_ops);


--
-- Name: idx_rule_active; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_rule_active ON public.rule USING btree (is_active);


--
-- Name: idx_rule_attribute_attribute; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_rule_attribute_attribute ON public.rule_attribute USING btree (attribute_id);


--
-- Name: idx_rule_attribute_rule; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_rule_attribute_rule ON public.rule_attribute USING btree (rule_id);


--
-- Name: idx_rule_type; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_rule_type ON public.rule USING btree (type);


--
-- Name: idx_score_data_application; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_score_data_application ON public.score_data USING btree (application_id);


--
-- Name: idx_score_data_user_active; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_score_data_user_active ON public.score_data USING btree (user_id, is_active);


--
-- Name: idx_score_data_user_category; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_score_data_user_category ON public.score_data USING btree (user_id, category_id);


--
-- Name: idx_template_active; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_template_active ON public.template USING btree (is_active);


--
-- Name: idx_template_category; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_template_category ON public.template USING btree (category_id);


--
-- Name: idx_template_category_active; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_template_category_active ON public.template_category USING btree (is_active);


--
-- Name: idx_template_category_deleted; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_template_category_deleted ON public.template_category USING btree (is_deleted);


--
-- Name: idx_template_category_parent_sort; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_template_category_parent_sort ON public.template_category USING btree (parent_id, sort_order, id);


--
-- Name: idx_template_rule_rule; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_template_rule_rule ON public.template_rule USING btree (rule_id);


--
-- Name: idx_template_rule_template; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX idx_template_rule_template ON public.template_rule USING btree (template_id);


--
-- Name: ix_applications_user_id; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_applications_user_id ON public.applications USING btree (user_id);


--
-- Name: ix_embeddings_category; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_embeddings_category ON public.embeddings USING btree (category);


--
-- Name: ix_embeddings_category_ref_id; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_embeddings_category_ref_id ON public.embeddings USING btree (category, ref_id);


--
-- Name: ix_embeddings_ref_id; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_embeddings_ref_id ON public.embeddings USING btree (ref_id);


--
-- Name: ix_file_category_deleted; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_file_category_deleted ON public.file_metadata USING btree (file_category, is_deleted);


--
-- Name: ix_file_metadata_file_category; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_file_metadata_file_category ON public.file_metadata USING btree (file_category);


--
-- Name: ix_file_metadata_is_deleted; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_file_metadata_is_deleted ON public.file_metadata USING btree (is_deleted);


--
-- Name: ix_file_metadata_object_name; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_file_metadata_object_name ON public.file_metadata USING btree (object_name);


--
-- Name: ix_file_metadata_upload_user_id; Type: INDEX; Schema: public; Owner: zhouch
--

CREATE INDEX ix_file_metadata_upload_user_id ON public.file_metadata USING btree (upload_user_id);


--
-- Name: application_operation application_operation_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.application_operation
    ADD CONSTRAINT application_operation_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE;


--
-- Name: application_proofs application_proofs_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.application_proofs
    ADD CONSTRAINT application_proofs_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE;


--
-- Name: application_proofs application_proofs_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.application_proofs
    ADD CONSTRAINT application_proofs_file_id_fkey FOREIGN KEY (file_id) REFERENCES public.file_metadata(id);


--
-- Name: applications applications_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.template_category(id);


--
-- Name: applications applications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.applications
    ADD CONSTRAINT applications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: role_permission role_permission_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permission(id) ON DELETE CASCADE;


--
-- Name: role_permission role_permission_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id) ON DELETE CASCADE;


--
-- Name: rule_attribute rule_attribute_attribute_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.rule_attribute
    ADD CONSTRAINT rule_attribute_attribute_id_fkey FOREIGN KEY (attribute_id) REFERENCES public.attribute(id) ON DELETE CASCADE;


--
-- Name: rule_attribute rule_attribute_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.rule_attribute
    ADD CONSTRAINT rule_attribute_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.rule(id) ON DELETE CASCADE;


--
-- Name: score_data score_data_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.score_data
    ADD CONSTRAINT score_data_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.applications(id) ON DELETE CASCADE;


--
-- Name: score_data score_data_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.score_data
    ADD CONSTRAINT score_data_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.template_category(id);


--
-- Name: score_data score_data_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.score_data
    ADD CONSTRAINT score_data_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: template template_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.template_category(id) ON DELETE CASCADE;


--
-- Name: template_category template_category_parent_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template_category
    ADD CONSTRAINT template_category_parent_id_fkey FOREIGN KEY (parent_id) REFERENCES public.template_category(id) ON DELETE SET NULL;


--
-- Name: template_rule template_rule_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template_rule
    ADD CONSTRAINT template_rule_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.rule(id);


--
-- Name: template_rule template_rule_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.template_rule
    ADD CONSTRAINT template_rule_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE CASCADE;


--
-- Name: user_role user_role_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id) ON DELETE CASCADE;


--
-- Name: user_role user_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: zhouch
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict rRDFCyqDpGBgrdEdfNqYov1aXbhVRKfwrg7gypficpJvANpU1bjGFEFOdv8rw5g

