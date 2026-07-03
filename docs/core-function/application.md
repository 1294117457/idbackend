1.
CREATE TABLE score_applications (
    id            SERIAL PRIMARY KEY,
    user_id       INTEGER NOT NULL REFERENCES users(id),
    template_id   INTEGER NOT NULL REFERENCES template(id),
    category_id   INTEGER NOT NULL REFERENCES template_category(id),  -- 冗余，便于聚合
    template_name VARCHAR(100),    -- 快照，防模板改名影响历史
    apply_input   DECIMAL(10,4),   -- 用户输入值
    apply_score   DECIMAL(5,2),    -- 计算引擎自动算出，不由用户填写
    gain_score    DECIMAL(5,2),    -- 审批通过的所有 proof 的 proof_value 之和
    status        INTEGER DEFAULT 0, -- 0=待审核 1=通过 2=驳回 4=撤回
    review_count  INTEGER DEFAULT 1,
    remark        TEXT,
    created_at    TIMESTAMP,
    updated_at    TIMESTAMP
);

CREATE TABLE application_proofs (
    id             SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES score_applications(id) ON DELETE CASCADE,
    proof_file_id  INTEGER NOT NULL REFERENCES file_metadata(id),
    proof_value    DECIMAL(5,2),   -- 该证明材料对应的分值
    review_count   INTEGER DEFAULT 1,
    approved_count INTEGER DEFAULT 0,
    status         INTEGER DEFAULT 0,
    review_records JSON,
    remark         VARCHAR(500),
    created_at     TIMESTAMP,
    updated_at     TIMESTAMP
);
application和proofs中，application是用户结合template提交申请
这里这里一方面你觉得是直接记录userid和username和templateid,templatename在application中号呢，还是只记录userid和templateid在applcation，需要对应信息时再查，前者application有点膨胀，后者会不会性能不好？
然后是不是实际只需要记录apply_score,等于用户最后通过模板计算得到的分数和gain_socre基于审批通过的proofs获得分数，
然后status是不是可以改为枚举而不是integer，然后评价是不是可以单独再拆分一个数据对象application_remark，这里有点耦合，然后改为记录remarkId，
最后总的就是id,name,userid,templateid,apply_score,gain_score,status,review_count,approved_count
然后remark需要哪些字段呢，我想的时评价人的id，评价人的name，applicationId,userid，content，其中content作为文本你觉得怎么样
然后一个application可以有多个remark，具体你觉得该怎么做呢，我不太了解remark怎么实现给我点建议

然后proofs，一个application可能有多个甚至上百个proof，每个proof需要有对应的id,applicationid,proof_socre,绑定对应的证明材料，approved_count，review_count,status,

你觉得怎么样呢，然后实际需要达到的是，每个材料都可以被单独审核，当approved_count达到review_count时，这个proofs通过，分数累加到application的gained_score上；
然后application可以存在gained_score不等于review_count的情况，比如多个材料中部分没通过，但是整体申请被通过了，则status状态从APPLYING改为PASS,如果用户不同意则可对单个proof进行修改，然后重新提交申请REAPPLY或者如果用户同意，status改为CONFIRMED
你觉得怎么样呢

CREATE TABLE score_applications (
    id             SERIAL PRIMARY KEY,
    user_id        INTEGER NOT NULL REFERENCES users(id),
    template_id    INTEGER NOT NULL REFERENCES template(id),
    template_name  VARCHAR(100) NOT NULL,
    category_id    INTEGER NOT NULL REFERENCES template_category(id),
    apply_score    DECIMAL(5,2),
    gain_score     DECIMAL(5,2) DEFAULT 0,
    status         VARCHAR(20) DEFAULT 'DRAFT'
                   CHECK (status IN ('DRAFT','APPLYING','PASSED','REJECTED')),
    review_count   INTEGER DEFAULT 1,
    approved_count INTEGER DEFAULT 0,
    created_at     TIMESTAMP,
    updated_at     TIMESTAMP
);
CREATE INDEX idx_application_user   ON score_applications(user_id);
CREATE INDEX idx_application_status ON score_applications(status);
CREATE TABLE application_proofs (
    id             SERIAL PRIMARY KEY,
    application_id INTEGER NOT NULL REFERENCES score_applications(id) ON DELETE CASCADE,
    file_id        INTEGER NOT NULL REFERENCES file_metadata(id),
    proof_score    DECIMAL(5,2) NOT NULL,
    status         VARCHAR(20) DEFAULT 'PENDING'
                   CHECK (status IN ('PENDING','APPROVED','REJECTED')),
    created_at     TIMESTAMP,
    updated_at     TIMESTAMP
);
CREATE INDEX idx_proofs_application ON application_proofs(application_id);

CREATE TABLE application_operation (
    id               SERIAL PRIMARY KEY,
    application_id   INTEGER NOT NULL REFERENCES score_applications(id),
    operator_id      INTEGER NOT NULL,
    operator_name    VARCHAR(100) NOT NULL,
    operation        VARCHAR(30) NOT NULL
                     CHECK (operation IN ('SUBMIT','REVIEW_PROOF','PASS','REJECT','RESUBMIT')),
    remark           TEXT,
    created_at       TIMESTAMP DEFAULT NOW()
);
CREATE INDEX idx_operation_application ON application_operation(application_id);