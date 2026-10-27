CREATE TABLE audit_logs (
	id VARCHAR(36) NOT NULL, 
	entity_type VARCHAR(50) NOT NULL, 
	entity_id VARCHAR(36) NOT NULL, 
	action VARCHAR(50) NOT NULL, 
	detail TEXT, 
	actor VARCHAR(80) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE employee_payments (
	id VARCHAR(36) NOT NULL, 
	employee_id VARCHAR(36) NOT NULL, 
	payment_date DATE NOT NULL, 
	amount_kurus INTEGER NOT NULL, 
	payment_type VARCHAR(7) NOT NULL, 
	note TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(employee_id) REFERENCES employees (id) ON DELETE RESTRICT
);
CREATE TABLE employees (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	phone VARCHAR(40), 
	role VARCHAR(120), 
	daily_rate_kurus INTEGER, 
	note TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE material_movements (
	id VARCHAR(36) NOT NULL, 
	material_id VARCHAR(36) NOT NULL, 
	project_id VARCHAR(36), 
	purchase_id VARCHAR(36), 
	movement_date DATE NOT NULL, 
	movement_type VARCHAR(10) NOT NULL, 
	quantity NUMERIC(18, 3), 
	unit VARCHAR(24), 
	amount_kurus INTEGER, 
	confidence VARCHAR(10) NOT NULL, 
	note TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(material_id) REFERENCES materials (id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	FOREIGN KEY(purchase_id) REFERENCES purchases (id) ON DELETE RESTRICT
);
CREATE TABLE materials (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	default_unit VARCHAR(24) NOT NULL, 
	tracking_mode VARCHAR(10) NOT NULL, 
	note TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE payments (
	id VARCHAR(36) NOT NULL, 
	supplier_id VARCHAR(36) NOT NULL, 
	purchase_id VARCHAR(36), 
	payment_date DATE NOT NULL, 
	amount_kurus INTEGER NOT NULL, 
	note TEXT, 
	idempotency_key VARCHAR(80) NOT NULL, 
	status VARCHAR(9) NOT NULL, 
	reversed_at DATETIME, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id) ON DELETE RESTRICT, 
	FOREIGN KEY(purchase_id) REFERENCES purchases (id) ON DELETE RESTRICT, 
	UNIQUE (idempotency_key)
);
CREATE TABLE project_expenses (
	id VARCHAR(36) NOT NULL, 
	project_id VARCHAR(36) NOT NULL, 
	site_id VARCHAR(36), 
	expense_date DATE NOT NULL, 
	category VARCHAR(12) NOT NULL, 
	amount_kurus INTEGER NOT NULL, 
	description TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	FOREIGN KEY(site_id) REFERENCES sites (id) ON DELETE RESTRICT
);
CREATE TABLE projects (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	customer_name VARCHAR(180) NOT NULL, 
	contract_amount_kurus INTEGER, 
	budget_kurus INTEGER, 
	project_state VARCHAR(32) NOT NULL, 
	note TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE purchases (
	id VARCHAR(36) NOT NULL, 
	supplier_id VARCHAR(36) NOT NULL, 
	material_id VARCHAR(36) NOT NULL, 
	project_id VARCHAR(36), 
	purchase_date DATE NOT NULL, 
	due_date DATE, 
	quantity NUMERIC(18, 3), 
	unit VARCHAR(24), 
	unit_price_kurus INTEGER, 
	total_kurus INTEGER NOT NULL, 
	description TEXT, 
	idempotency_key VARCHAR(80) NOT NULL, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id) ON DELETE RESTRICT, 
	FOREIGN KEY(material_id) REFERENCES materials (id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	UNIQUE (idempotency_key)
);
CREATE TABLE sites (
	id VARCHAR(36) NOT NULL, 
	project_id VARCHAR(36), 
	name VARCHAR(180) NOT NULL, 
	address TEXT, 
	note TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT
);
CREATE TABLE suppliers (
	id VARCHAR(36) NOT NULL, 
	name VARCHAR(180) NOT NULL, 
	phone VARCHAR(40), 
	note TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE work_logs (
	id VARCHAR(36) NOT NULL, 
	employee_id VARCHAR(36) NOT NULL, 
	project_id VARCHAR(36), 
	site_id VARCHAR(36), 
	work_date DATE NOT NULL, 
	hours NUMERIC(5, 2) NOT NULL, 
	amount_kurus INTEGER NOT NULL, 
	note TEXT, 
	status VARCHAR(9) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(employee_id) REFERENCES employees (id) ON DELETE RESTRICT, 
	FOREIGN KEY(project_id) REFERENCES projects (id) ON DELETE RESTRICT, 
	FOREIGN KEY(site_id) REFERENCES sites (id) ON DELETE RESTRICT
);
CREATE INDEX ix_audit_entity ON audit_logs (entity_type, entity_id);
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);
CREATE INDEX ix_employee_payment_date ON employee_payments (employee_id, payment_date);
CREATE INDEX ix_employee_payments_payment_date ON employee_payments (payment_date);
CREATE INDEX ix_employee_payments_payment_type ON employee_payments (payment_type);
CREATE INDEX ix_employee_payments_status ON employee_payments (status);
CREATE INDEX ix_employees_name ON employees (name);
CREATE INDEX ix_employees_status ON employees (status);
CREATE INDEX ix_material_movements_movement_date ON material_movements (movement_date);
CREATE INDEX ix_material_movements_movement_type ON material_movements (movement_type);
CREATE INDEX ix_material_movements_status ON material_movements (status);
CREATE UNIQUE INDEX ix_materials_name ON materials (name);
CREATE INDEX ix_materials_status ON materials (status);
CREATE INDEX ix_movement_material_date ON material_movements (material_id, movement_date);
CREATE INDEX ix_movement_project_date ON material_movements (project_id, movement_date);
CREATE INDEX ix_payment_purchase_date ON payments (purchase_id, payment_date);
CREATE INDEX ix_payment_supplier_date ON payments (supplier_id, payment_date);
CREATE INDEX ix_payments_payment_date ON payments (payment_date);
CREATE INDEX ix_payments_status ON payments (status);
CREATE INDEX ix_project_expense_date ON project_expenses (project_id, expense_date);
CREATE INDEX ix_project_expenses_expense_date ON project_expenses (expense_date);
CREATE INDEX ix_project_expenses_status ON project_expenses (status);
CREATE INDEX ix_projects_customer_name ON projects (customer_name);
CREATE INDEX ix_projects_name ON projects (name);
CREATE INDEX ix_projects_project_state ON projects (project_state);
CREATE INDEX ix_projects_status ON projects (status);
CREATE INDEX ix_purchase_project_date ON purchases (project_id, purchase_date);
CREATE INDEX ix_purchase_supplier_date ON purchases (supplier_id, purchase_date);
CREATE INDEX ix_purchases_due_date ON purchases (due_date);
CREATE INDEX ix_purchases_purchase_date ON purchases (purchase_date);
CREATE INDEX ix_purchases_status ON purchases (status);
CREATE INDEX ix_sites_name ON sites (name);
CREATE INDEX ix_sites_status ON sites (status);
CREATE UNIQUE INDEX ix_suppliers_name ON suppliers (name);
CREATE INDEX ix_suppliers_status ON suppliers (status);
CREATE INDEX ix_work_log_employee_date ON work_logs (employee_id, work_date);
CREATE INDEX ix_work_log_project_date ON work_logs (project_id, work_date);
CREATE INDEX ix_work_logs_status ON work_logs (status);
CREATE INDEX ix_work_logs_work_date ON work_logs (work_date);
