-- ============================================
-- Office_Agent 数据库表结构 DDL
-- 数据库: office_agent_ai
-- 字符集: utf8mb4
-- ============================================

CREATE DATABASE IF NOT EXISTS `office_agent_ai`
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_unicode_ci;

USE `office_agent_ai`;

-- ── 公司 ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS `company` (
  `id`          VARCHAR(32)   NOT NULL COMMENT 'UUID',
  `name`        VARCHAR(100)  NOT NULL COMMENT '公司名称',
  `description` TEXT          DEFAULT NULL COMMENT '描述',
  `created_at`  DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='公司';

-- ── 部门 ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS `department` (
  `id`          VARCHAR(32)   NOT NULL,
  `company_id`  VARCHAR(32)   NOT NULL COMMENT '所属公司',
  `name`        VARCHAR(100)  NOT NULL COMMENT '部门名称',
  `emoji`       VARCHAR(10)   NOT NULL DEFAULT '📦' COMMENT '部门图标',
  `description` TEXT          DEFAULT NULL,
  `created_at`  DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_department_company` (`company_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='部门';

-- ── 领域 ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS `domain` (
  `id`            VARCHAR(32)   NOT NULL,
  `department_id` VARCHAR(32)   NOT NULL COMMENT '所属部门',
  `name`          VARCHAR(100)  NOT NULL COMMENT '领域名称',
  `description`   TEXT          DEFAULT NULL,
  `created_at`    DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_domain_dept` (`department_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='领域';

-- ── 岗位包 ───────────────────────────────────
CREATE TABLE IF NOT EXISTS `role_pack` (
  `id`         VARCHAR(32)   NOT NULL,
  `name`       VARCHAR(100)  NOT NULL COMMENT '岗位名称',
  `version`    VARCHAR(20)   NOT NULL DEFAULT '1.0.0',
  `owner`      VARCHAR(100)  DEFAULT NULL,
  `config`     JSON          DEFAULT NULL COMMENT 'YAML/JSON 配置',
  `created_at` DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='岗位包（Role Pack）';

-- ── AI 员工 ──────────────────────────────────
CREATE TABLE IF NOT EXISTS `agent` (
  `id`             VARCHAR(32)   NOT NULL,
  `name`           VARCHAR(100)  NOT NULL COMMENT '员工姓名',
  `title`          VARCHAR(200)  NOT NULL COMMENT '职位',
  `emoji`          VARCHAR(10)   NOT NULL DEFAULT '🧑‍💻',
  `department_id`  VARCHAR(32)   NOT NULL COMMENT '部门 ID',
  `domain_id`      VARCHAR(32)   NOT NULL COMMENT '领域 ID',
  `role_pack_id`   VARCHAR(32)   DEFAULT NULL COMMENT '岗位包 ID',

  -- 状态机: online / indexing / trial / pending_check / maintenance / restricted
  `status`         VARCHAR(20)   NOT NULL DEFAULT 'online',
  `version`        INT           NOT NULL DEFAULT 1,
  `owner`          VARCHAR(100)  DEFAULT NULL COMMENT '负责人',

  -- 描述与配置
  `description`    TEXT          DEFAULT NULL,
  `resources`      JSON          DEFAULT NULL COMMENT '关联资源列表',
  `tags`           JSON          DEFAULT NULL COMMENT '标签（部门/领域）',

  -- Harness Engineering：行为准则 + 直绑能力
  `agents_md`      TEXT          DEFAULT NULL COMMENT 'AGENTS.md 行为准则',
  `skills`         JSON          DEFAULT NULL COMMENT '直绑 skill_key 列表（优先于岗位包）',

  -- 指标
  `adoption_rate`  INT           NOT NULL DEFAULT 0 COMMENT '采纳率 %',
  `session_count`  INT           NOT NULL DEFAULT 0 COMMENT '会话总数',

  `created_at`     DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `updated_at`     DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_agent_dept` (`department_id`),
  INDEX `idx_agent_domain` (`domain_id`),
  INDEX `idx_agent_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI 员工';

-- ── 会话 ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS `session` (
  `id`         VARCHAR(32)   NOT NULL,
  `user_id`    VARCHAR(32)   NOT NULL DEFAULT 'guest',
  `title`      VARCHAR(200)  DEFAULT NULL,
  `state`      VARCHAR(20)   NOT NULL DEFAULT 'active' COMMENT 'active/closed',
  `created_at` DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_session_user` (`user_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话';

-- ── 消息 ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS `message` (
  `id`           VARCHAR(32)   NOT NULL,
  `session_id`   VARCHAR(32)   NOT NULL,
  `role`         VARCHAR(20)   NOT NULL COMMENT 'user/assistant/system',
  `content`      MEDIUMTEXT    NOT NULL,
  `agent_id`     VARCHAR(32)   DEFAULT NULL,
  `evidence_ids` JSON          DEFAULT NULL,
  `confidence`   VARCHAR(20)   DEFAULT NULL COMMENT 'HIGH/MEDIUM/LOW',
  `created_at`   DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_msg_session` (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='消息';

-- ── 协作任务卡 ───────────────────────────────
CREATE TABLE IF NOT EXISTS `task_card` (
  `id`               VARCHAR(32)   NOT NULL,
  `title`            VARCHAR(300)  NOT NULL,
  `description`      TEXT          DEFAULT NULL,
  `state`            VARCHAR(20)   NOT NULL DEFAULT 'in_progress' COMMENT 'in_progress/completed',
  `initiator`        VARCHAR(100)  DEFAULT NULL,
  `deadline_minutes` INT           NOT NULL DEFAULT 30,
  `tags`             JSON          DEFAULT NULL,
  `conflict_note`    TEXT          DEFAULT NULL COMMENT '冲突或汇总结论',
  `created_at`       DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_task_state` (`state`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='协作任务卡';

-- ── 子任务分配 ───────────────────────────────
CREATE TABLE IF NOT EXISTS `task_assignment` (
  `id`            VARCHAR(32)   NOT NULL,
  `task_card_id`  VARCHAR(32)   NOT NULL,
  `agent_id`      VARCHAR(32)   NOT NULL,
  `agent_name`    VARCHAR(100)  NOT NULL,
  `agent_emoji`   VARCHAR(10)   NOT NULL DEFAULT '🧑‍💻',
  `department`    VARCHAR(100)  DEFAULT NULL,
  `domain`        VARCHAR(100)  DEFAULT NULL,
  `subtask_title` VARCHAR(300)  NOT NULL,
  `subtask_detail` TEXT         DEFAULT NULL,
  `status`        VARCHAR(20)   NOT NULL DEFAULT 'analyzing' COMMENT 'submitted/analyzing/clarify',
  `confidence`    VARCHAR(20)   DEFAULT NULL COMMENT 'HIGH/MEDIUM/LOW',
  `created_at`    DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_assign_task` (`task_card_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='子任务分配';

-- ── 知识候选 ─────────────────────────────────
CREATE TABLE IF NOT EXISTS `knowledge_candidate` (
  `id`               VARCHAR(32)   NOT NULL,
  `title`            VARCHAR(300)  NOT NULL,
  `domain`           VARCHAR(100)  DEFAULT NULL,
  `department`       VARCHAR(100)  DEFAULT NULL,
  `icon`             VARCHAR(10)   NOT NULL DEFAULT '📘',
  `status`           VARCHAR(20)   NOT NULL DEFAULT 'pending_review' COMMENT 'published/expired/pending_review',
  `owner`            VARCHAR(100)  DEFAULT NULL,
  `confidence`       VARCHAR(10)   NOT NULL DEFAULT 'MEDIUM',
  `published_at`     VARCHAR(20)   DEFAULT NULL COMMENT '发布日期 YYYY-MM-DD',
  `conflict_warning` TEXT          DEFAULT NULL,
  `created_at`       DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_knowledge_status` (`status`),
  INDEX `idx_knowledge_domain` (`domain`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识候选';

-- ── 证据 ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS `evidence` (
  `id`                 VARCHAR(32)   NOT NULL,
  `agent_id`           VARCHAR(32)   DEFAULT NULL,
  `source_type`        VARCHAR(20)   NOT NULL DEFAULT 'CODE' COMMENT 'CODE/DOC/GRAPH/CONFIG',
  `source_ref`         VARCHAR(500)  DEFAULT NULL,
  `excerpt`            TEXT          DEFAULT NULL,
  `verification_status` VARCHAR(20)  NOT NULL DEFAULT 'VERIFIED',
  `line_start`         INT           DEFAULT NULL,
  `line_end`           INT           DEFAULT NULL,
  `created_at`         DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  INDEX `idx_evidence_agent` (`agent_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='证据';
