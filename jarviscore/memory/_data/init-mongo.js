db = db.getSiblingDB('admin');
db.auth('admin', 'admin123');

db = db.getSiblingDB('memory_os_e2e');
db.createCollection('dialogue_pages');

db.createUser({
  user: 'e2e_user',
  pwd: 'e2e_password_2024',
  roles: [{ role: 'readWrite', db: 'memory_os_e2e' }],
});