--
-- PostgreSQL database dump
--

\restrict QngPAl6I2TyBgPamQkrGztg8qMgniCmHWHdRNLLSDdXQOu2tQfPWk7rOdFwCxIC

-- Dumped from database version 16.14 (Debian 16.14-1.pgdg12+1)
-- Dumped by pg_dump version 16.14 (Ubuntu 16.14-0ubuntu0.24.04.1)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
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
-- Name: agent_sessions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.agent_sessions (
    user_id integer NOT NULL,
    session_id character varying(100) NOT NULL,
    session_metadata json,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.agent_sessions OWNER TO postgres;

--
-- Name: agent_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.agent_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.agent_sessions_id_seq OWNER TO postgres;

--
-- Name: agent_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.agent_sessions_id_seq OWNED BY public.agent_sessions.id;


--
-- Name: application_proofs; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.application_proofs (
    application_id integer NOT NULL,
    proof_file_id integer NOT NULL,
    proof_value double precision NOT NULL,
    review_count integer NOT NULL,
    approved_count integer NOT NULL,
    status integer NOT NULL,
    reviewer_ids json,
    review_records json,
    remark character varying(500),
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.application_proofs OWNER TO postgres;

--
-- Name: application_proofs_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.application_proofs_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.application_proofs_id_seq OWNER TO postgres;

--
-- Name: application_proofs_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.application_proofs_id_seq OWNED BY public.application_proofs.id;


--
-- Name: attribute; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.attribute (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    group_code character varying(50) NOT NULL,
    group_name character varying(100) NOT NULL,
    type character varying(20) DEFAULT 'CONDITION'::character varying NOT NULL,
    value text DEFAULT ''::text NOT NULL,
    input_min numeric(10,4),
    input_max numeric(10,4),
    sort_order integer DEFAULT 0 NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    CONSTRAINT ck_attribute_type_enum CHECK (((type)::text = ANY ((ARRAY['CONDITION'::character varying, 'TRANSFORM'::character varying])::text[])))
);


ALTER TABLE public.attribute OWNER TO postgres;

--
-- Name: attribute_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.attribute_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.attribute_id_seq OWNER TO postgres;

--
-- Name: attribute_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.attribute_id_seq OWNED BY public.attribute.id;


--
-- Name: demand_applications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.demand_applications (
    student_id character varying(255) NOT NULL,
    application_data json NOT NULL,
    submit_time timestamp without time zone,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.demand_applications OWNER TO postgres;

--
-- Name: demand_applications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.demand_applications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.demand_applications_id_seq OWNER TO postgres;

--
-- Name: demand_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.demand_applications_id_seq OWNED BY public.demand_applications.id;


--
-- Name: demand_templates_bak; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.demand_templates_bak (
    template_name character varying(100),
    conditions json,
    description text,
    created_by character varying(50),
    is_active boolean,
    sort_order integer,
    id integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.demand_templates_bak OWNER TO postgres;

--
-- Name: evaluation_applications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.evaluation_applications (
    user_id integer NOT NULL,
    student_id character varying(20) NOT NULL,
    student_name character varying(100) NOT NULL,
    foreign_language_level character varying(200),
    disciplinary_violations integer NOT NULL,
    failed_courses integer NOT NULL,
    special_skills_remark text,
    attachment_files json,
    application_reason text,
    status character varying(20) NOT NULL,
    required_approvals integer NOT NULL,
    current_approvals integer NOT NULL,
    approval_records json,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.evaluation_applications OWNER TO postgres;

--
-- Name: evaluation_applications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.evaluation_applications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.evaluation_applications_id_seq OWNER TO postgres;

--
-- Name: evaluation_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.evaluation_applications_id_seq OWNED BY public.evaluation_applications.id;


--
-- Name: field_config_bak; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.field_config_bak (
    field_key character varying(50),
    display_name character varying(100),
    field_type character varying(20),
    max_score numeric(5,2),
    conditions json,
    description character varying(255),
    college_code character varying(50),
    academic_year integer,
    sort_order integer,
    is_active boolean,
    created_by character varying(50),
    id integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.field_config_bak OWNER TO postgres;

--
-- Name: field_subcategory_bak; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.field_subcategory_bak (
    field_id integer,
    sub_key character varying(50),
    display_name character varying(100),
    max_score numeric(5,2),
    description character varying(255),
    sort_order integer,
    is_active boolean,
    id integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.field_subcategory_bak OWNER TO postgres;

--
-- Name: file_metadata; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.file_metadata (
    object_name character varying(255) NOT NULL,
    original_name character varying(255) NOT NULL,
    file_size integer NOT NULL,
    content_type character varying(100),
    file_extension character varying(10),
    file_category character varying(50) NOT NULL,
    upload_user_id integer NOT NULL,
    is_deleted boolean NOT NULL,
    delete_time character varying(50),
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.file_metadata OWNER TO postgres;

--
-- Name: file_metadata_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.file_metadata_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.file_metadata_id_seq OWNER TO postgres;

--
-- Name: file_metadata_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.file_metadata_id_seq OWNED BY public.file_metadata.id;


--
-- Name: permission; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.permission (
    permission_code character varying(100) NOT NULL,
    permission_name character varying(100) NOT NULL,
    description character varying(255),
    sort_order integer NOT NULL,
    status boolean NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    api_path character varying(255)
);


ALTER TABLE public.permission OWNER TO postgres;

--
-- Name: permission_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.permission_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.permission_id_seq OWNER TO postgres;

--
-- Name: permission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.permission_id_seq OWNED BY public.permission.id;


--
-- Name: policy_documents; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.policy_documents (
    title character varying(200) NOT NULL,
    content character varying NOT NULL,
    category character varying(50),
    source_url character varying(500),
    embedding character varying,
    doc_metadata json,
    is_active boolean NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.policy_documents OWNER TO postgres;

--
-- Name: policy_documents_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.policy_documents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.policy_documents_id_seq OWNER TO postgres;

--
-- Name: policy_documents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.policy_documents_id_seq OWNED BY public.policy_documents.id;


--
-- Name: role; Type: TABLE; Schema: public; Owner: postgres
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


ALTER TABLE public.role OWNER TO postgres;

--
-- Name: role_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.role_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.role_id_seq OWNER TO postgres;

--
-- Name: role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.role_id_seq OWNED BY public.role.id;


--
-- Name: role_permission; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.role_permission (
    role_id integer NOT NULL,
    permission_id integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.role_permission OWNER TO postgres;

--
-- Name: role_permission_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.role_permission_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.role_permission_id_seq OWNER TO postgres;

--
-- Name: role_permission_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.role_permission_id_seq OWNED BY public.role_permission.id;


--
-- Name: rule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.rule (
    id integer NOT NULL,
    type character varying(20) DEFAULT 'CONDITION'::character varying NOT NULL,
    score numeric(5,2),
    name character varying(100) NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    CONSTRAINT ck_rule_type_enum CHECK (((type)::text = ANY ((ARRAY['CONDITION'::character varying, 'TRANSFORM'::character varying])::text[])))
);


ALTER TABLE public.rule OWNER TO postgres;

--
-- Name: rule_attribute; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.rule_attribute (
    id integer NOT NULL,
    rule_id integer NOT NULL,
    attribute_id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.rule_attribute OWNER TO postgres;

--
-- Name: rule_attribute_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.rule_attribute_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rule_attribute_id_seq OWNER TO postgres;

--
-- Name: rule_attribute_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.rule_attribute_id_seq OWNED BY public.rule_attribute.id;


--
-- Name: rule_attribute_mapping_bak; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.rule_attribute_mapping_bak (
    rule_id integer,
    attribute_id integer,
    is_required boolean,
    display_order integer,
    id integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.rule_attribute_mapping_bak OWNER TO postgres;

--
-- Name: rule_attributes_bak; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.rule_attributes_bak (
    attribute_code character varying(50),
    attribute_type character varying(20),
    attribute_value text,
    input_max numeric(10,4),
    input_min numeric(10,4),
    input_interval character varying(20),
    display_order integer,
    description text,
    is_active boolean,
    id integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.rule_attributes_bak OWNER TO postgres;

--
-- Name: rule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.rule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rule_id_seq OWNER TO postgres;

--
-- Name: rule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.rule_id_seq OWNED BY public.rule.id;


--
-- Name: score_applications; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.score_applications (
    user_id integer NOT NULL,
    student_id character varying(50) NOT NULL,
    student_name character varying(100),
    major character varying(100),
    enrollment_year integer,
    template_name character varying(100) NOT NULL,
    score_type integer NOT NULL,
    apply_score double precision NOT NULL,
    gain_score double precision,
    status integer NOT NULL,
    review_count integer NOT NULL,
    current_review_count integer NOT NULL,
    reviewer_ids json,
    review_records json,
    remark text,
    apply_input double precision,
    proofs_input double precision NOT NULL,
    rule_id integer,
    template_id integer,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.score_applications OWNER TO postgres;

--
-- Name: score_applications_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.score_applications_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.score_applications_id_seq OWNER TO postgres;

--
-- Name: score_applications_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.score_applications_id_seq OWNED BY public.score_applications.id;


--
-- Name: score_template_rules_bak; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.score_template_rules_bak (
    template_id integer,
    rule_type character varying(20),
    rule_name character varying(100),
    rule_score numeric(5,2),
    priority integer,
    description text,
    id integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.score_template_rules_bak OWNER TO postgres;

--
-- Name: score_templates_bak; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.score_templates_bak (
    template_name character varying(100),
    template_type character varying(20),
    score_type integer,
    template_max_score numeric(5,2),
    input_unit character varying(50),
    description text,
    created_by character varying(50),
    is_active boolean,
    review_count integer,
    field_id integer,
    subcategory_id integer,
    id integer,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    category_id integer
);


ALTER TABLE public.score_templates_bak OWNER TO postgres;

--
-- Name: system_config; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.system_config (
    config_key character varying(100) NOT NULL,
    config_value character varying(500) NOT NULL,
    description character varying(200),
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.system_config OWNER TO postgres;

--
-- Name: system_config_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.system_config_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.system_config_id_seq OWNER TO postgres;

--
-- Name: system_config_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.system_config_id_seq OWNED BY public.system_config.id;


--
-- Name: template; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.template (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    category_id integer NOT NULL,
    max_score numeric(5,2) NOT NULL,
    review_count integer DEFAULT 1 NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    description text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    CONSTRAINT ck_template_max_score_nonneg CHECK ((max_score >= (0)::numeric))
);


ALTER TABLE public.template OWNER TO postgres;

--
-- Name: template_category; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.template_category (
    id integer NOT NULL,
    name character varying(100) NOT NULL,
    parent_id integer,
    max_score numeric(5,2) NOT NULL,
    is_bind_template boolean DEFAULT false NOT NULL,
    sort_order integer DEFAULT 0 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    description character varying(255),
    created_at timestamp without time zone,
    updated_at timestamp without time zone,
    CONSTRAINT ck_template_category_max_score_nonneg CHECK ((max_score >= (0)::numeric))
);


ALTER TABLE public.template_category OWNER TO postgres;

--
-- Name: template_category_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.template_category_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.template_category_id_seq OWNER TO postgres;

--
-- Name: template_category_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.template_category_id_seq OWNED BY public.template_category.id;


--
-- Name: template_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.template_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.template_id_seq OWNER TO postgres;

--
-- Name: template_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.template_id_seq OWNED BY public.template.id;


--
-- Name: template_rule; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.template_rule (
    id integer NOT NULL,
    template_id integer NOT NULL,
    rule_id integer NOT NULL,
    created_at timestamp without time zone,
    updated_at timestamp without time zone
);


ALTER TABLE public.template_rule OWNER TO postgres;

--
-- Name: template_rule_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.template_rule_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.template_rule_id_seq OWNER TO postgres;

--
-- Name: template_rule_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.template_rule_id_seq OWNED BY public.template_rule.id;


--
-- Name: user_role; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.user_role (
    user_id integer NOT NULL,
    role_id integer NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.user_role OWNER TO postgres;

--
-- Name: user_role_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.user_role_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.user_role_id_seq OWNER TO postgres;

--
-- Name: user_role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.user_role_id_seq OWNED BY public.user_role.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
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
    student_id character varying(50),
    gpa double precision,
    is_confirmed boolean NOT NULL,
    demand_value json,
    demand_files json,
    academic_score double precision NOT NULL,
    specialty_score double precision NOT NULL,
    comprehensive_score double precision NOT NULL,
    id integer NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: agent_sessions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_sessions ALTER COLUMN id SET DEFAULT nextval('public.agent_sessions_id_seq'::regclass);


--
-- Name: application_proofs id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.application_proofs ALTER COLUMN id SET DEFAULT nextval('public.application_proofs_id_seq'::regclass);


--
-- Name: attribute id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attribute ALTER COLUMN id SET DEFAULT nextval('public.attribute_id_seq'::regclass);


--
-- Name: demand_applications id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.demand_applications ALTER COLUMN id SET DEFAULT nextval('public.demand_applications_id_seq'::regclass);


--
-- Name: evaluation_applications id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evaluation_applications ALTER COLUMN id SET DEFAULT nextval('public.evaluation_applications_id_seq'::regclass);


--
-- Name: file_metadata id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.file_metadata ALTER COLUMN id SET DEFAULT nextval('public.file_metadata_id_seq'::regclass);


--
-- Name: permission id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.permission ALTER COLUMN id SET DEFAULT nextval('public.permission_id_seq'::regclass);


--
-- Name: policy_documents id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.policy_documents ALTER COLUMN id SET DEFAULT nextval('public.policy_documents_id_seq'::regclass);


--
-- Name: role id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role ALTER COLUMN id SET DEFAULT nextval('public.role_id_seq'::regclass);


--
-- Name: role_permission id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permission ALTER COLUMN id SET DEFAULT nextval('public.role_permission_id_seq'::regclass);


--
-- Name: rule id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule ALTER COLUMN id SET DEFAULT nextval('public.rule_id_seq'::regclass);


--
-- Name: rule_attribute id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule_attribute ALTER COLUMN id SET DEFAULT nextval('public.rule_attribute_id_seq'::regclass);


--
-- Name: score_applications id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.score_applications ALTER COLUMN id SET DEFAULT nextval('public.score_applications_id_seq'::regclass);


--
-- Name: system_config id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_config ALTER COLUMN id SET DEFAULT nextval('public.system_config_id_seq'::regclass);


--
-- Name: template id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template ALTER COLUMN id SET DEFAULT nextval('public.template_id_seq'::regclass);


--
-- Name: template_category id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template_category ALTER COLUMN id SET DEFAULT nextval('public.template_category_id_seq'::regclass);


--
-- Name: template_rule id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template_rule ALTER COLUMN id SET DEFAULT nextval('public.template_rule_id_seq'::regclass);


--
-- Name: user_role id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_role ALTER COLUMN id SET DEFAULT nextval('public.user_role_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: agent_sessions agent_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_pkey PRIMARY KEY (id);


--
-- Name: agent_sessions agent_sessions_session_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.agent_sessions
    ADD CONSTRAINT agent_sessions_session_id_key UNIQUE (session_id);


--
-- Name: application_proofs application_proofs_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.application_proofs
    ADD CONSTRAINT application_proofs_pkey PRIMARY KEY (id);


--
-- Name: attribute attribute_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.attribute
    ADD CONSTRAINT attribute_pkey PRIMARY KEY (id);


--
-- Name: demand_applications demand_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.demand_applications
    ADD CONSTRAINT demand_applications_pkey PRIMARY KEY (id);


--
-- Name: demand_applications demand_applications_student_id_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.demand_applications
    ADD CONSTRAINT demand_applications_student_id_key UNIQUE (student_id);


--
-- Name: evaluation_applications evaluation_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evaluation_applications
    ADD CONSTRAINT evaluation_applications_pkey PRIMARY KEY (id);


--
-- Name: file_metadata file_metadata_object_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.file_metadata
    ADD CONSTRAINT file_metadata_object_name_key UNIQUE (object_name);


--
-- Name: file_metadata file_metadata_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.file_metadata
    ADD CONSTRAINT file_metadata_pkey PRIMARY KEY (id);


--
-- Name: permission permission_permission_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.permission
    ADD CONSTRAINT permission_permission_code_key UNIQUE (permission_code);


--
-- Name: permission permission_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.permission
    ADD CONSTRAINT permission_pkey PRIMARY KEY (id);


--
-- Name: policy_documents policy_documents_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.policy_documents
    ADD CONSTRAINT policy_documents_pkey PRIMARY KEY (id);


--
-- Name: role_permission role_permission_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_pkey PRIMARY KEY (id);


--
-- Name: role_permission role_permission_role_id_permission_id_unique; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_role_id_permission_id_unique UNIQUE (role_id, permission_id);


--
-- Name: role role_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_pkey PRIMARY KEY (id);


--
-- Name: role role_role_code_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_role_code_key UNIQUE (role_code);


--
-- Name: rule_attribute rule_attribute_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule_attribute
    ADD CONSTRAINT rule_attribute_pkey PRIMARY KEY (id);


--
-- Name: rule rule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule
    ADD CONSTRAINT rule_pkey PRIMARY KEY (id);


--
-- Name: score_applications score_applications_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.score_applications
    ADD CONSTRAINT score_applications_pkey PRIMARY KEY (id);


--
-- Name: system_config system_config_config_key_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_config_key_key UNIQUE (config_key);


--
-- Name: system_config system_config_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_config
    ADD CONSTRAINT system_config_pkey PRIMARY KEY (id);


--
-- Name: template_category template_category_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template_category
    ADD CONSTRAINT template_category_pkey PRIMARY KEY (id);


--
-- Name: template template_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_pkey PRIMARY KEY (id);


--
-- Name: template_rule template_rule_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template_rule
    ADD CONSTRAINT template_rule_pkey PRIMARY KEY (id);


--
-- Name: rule_attribute uk_rule_attribute; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule_attribute
    ADD CONSTRAINT uk_rule_attribute UNIQUE (rule_id, attribute_id);


--
-- Name: template_rule uk_template_rule; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template_rule
    ADD CONSTRAINT uk_template_rule UNIQUE (template_id, rule_id);


--
-- Name: user_role user_role_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_pkey PRIMARY KEY (id);


--
-- Name: user_role user_role_user_id_role_id_unique; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_user_id_role_id_unique UNIQUE (user_id, role_id);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: users users_username_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_username_key UNIQUE (username);


--
-- Name: idx_attribute_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_attribute_active ON public.attribute USING btree (is_active);


--
-- Name: idx_attribute_group; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_attribute_group ON public.attribute USING btree (group_code);


--
-- Name: idx_permission_api_path; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_permission_api_path ON public.permission USING btree (api_path);


--
-- Name: idx_role_permission_permission_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_role_permission_permission_id ON public.role_permission USING btree (permission_id);


--
-- Name: idx_role_permission_role_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_role_permission_role_id ON public.role_permission USING btree (role_id);


--
-- Name: idx_rule_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_rule_active ON public.rule USING btree (is_active);


--
-- Name: idx_rule_attribute_attribute; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_rule_attribute_attribute ON public.rule_attribute USING btree (attribute_id);


--
-- Name: idx_rule_attribute_rule; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_rule_attribute_rule ON public.rule_attribute USING btree (rule_id);


--
-- Name: idx_rule_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_rule_type ON public.rule USING btree (type);


--
-- Name: idx_template_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_template_active ON public.template USING btree (is_active);


--
-- Name: idx_template_category; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_template_category ON public.template USING btree (category_id);


--
-- Name: idx_template_category_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_template_category_active ON public.template_category USING btree (is_active);


--
-- Name: idx_template_category_parent_sort; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_template_category_parent_sort ON public.template_category USING btree (parent_id, sort_order, id);


--
-- Name: idx_template_rule_rule; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_template_rule_rule ON public.template_rule USING btree (rule_id);


--
-- Name: idx_template_rule_template; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_template_rule_template ON public.template_rule USING btree (template_id);


--
-- Name: idx_user_role_role_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_role_role_id ON public.user_role USING btree (role_id);


--
-- Name: idx_user_role_user_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_user_role_user_id ON public.user_role USING btree (user_id);


--
-- Name: application_proofs application_proofs_application_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.application_proofs
    ADD CONSTRAINT application_proofs_application_id_fkey FOREIGN KEY (application_id) REFERENCES public.score_applications(id) ON DELETE CASCADE;


--
-- Name: application_proofs application_proofs_proof_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.application_proofs
    ADD CONSTRAINT application_proofs_proof_file_id_fkey FOREIGN KEY (proof_file_id) REFERENCES public.file_metadata(id);


--
-- Name: evaluation_applications evaluation_applications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.evaluation_applications
    ADD CONSTRAINT evaluation_applications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: score_applications fk_application_rule_v4; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.score_applications
    ADD CONSTRAINT fk_application_rule_v4 FOREIGN KEY (rule_id) REFERENCES public.rule(id);


--
-- Name: score_applications fk_application_template_v4; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.score_applications
    ADD CONSTRAINT fk_application_template_v4 FOREIGN KEY (template_id) REFERENCES public.template(id);


--
-- Name: template_category fk_template_category_parent; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template_category
    ADD CONSTRAINT fk_template_category_parent FOREIGN KEY (parent_id) REFERENCES public.template_category(id) ON DELETE CASCADE;


--
-- Name: role_permission role_permission_permission_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_permission_id_fkey FOREIGN KEY (permission_id) REFERENCES public.permission(id) ON DELETE CASCADE;


--
-- Name: role_permission role_permission_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.role_permission
    ADD CONSTRAINT role_permission_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id) ON DELETE CASCADE;


--
-- Name: rule_attribute rule_attribute_attribute_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule_attribute
    ADD CONSTRAINT rule_attribute_attribute_id_fkey FOREIGN KEY (attribute_id) REFERENCES public.attribute(id) ON DELETE CASCADE;


--
-- Name: rule_attribute rule_attribute_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rule_attribute
    ADD CONSTRAINT rule_attribute_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.rule(id) ON DELETE CASCADE;


--
-- Name: score_applications score_applications_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.score_applications
    ADD CONSTRAINT score_applications_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: template template_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.template_category(id) ON DELETE CASCADE;


--
-- Name: template_rule template_rule_rule_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template_rule
    ADD CONSTRAINT template_rule_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES public.rule(id);


--
-- Name: template_rule template_rule_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.template_rule
    ADD CONSTRAINT template_rule_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE CASCADE;


--
-- Name: user_role user_role_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id) ON DELETE CASCADE;


--
-- Name: user_role user_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict QngPAl6I2TyBgPamQkrGztg8qMgniCmHWHdRNLLSDdXQOu2tQfPWk7rOdFwCxIC

