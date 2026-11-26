from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from datetime import datetime, timedelta
import sqlite3, secrets, hashlib, hmac, os

ROOT=Path(__file__).resolve().parent
DB_PATH=ROOT/'menuflow.db'
app=FastAPI(title='MenuFlow multi-restaurante',version='2.0')
app.add_middleware(CORSMiddleware,allow_origins=['*'],allow_credentials=True,allow_methods=['*'],allow_headers=['*'])

def db():
 c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def now(): return datetime.now().isoformat(timespec='seconds')
def pw_hash(pw,salt=None):
 salt=salt or secrets.token_hex(16); return salt+':'+hashlib.pbkdf2_hmac('sha256',pw.encode(),salt.encode(),180000).hex()
def verify(pw,stored):
 try: salt,h=stored.split(':',1); return hmac.compare_digest(hashlib.pbkdf2_hmac('sha256',pw.encode(),salt.encode(),180000).hex(),h)
 except: return False

def init():
 with db() as c:
  c.executescript('''
  CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL,email TEXT NOT NULL UNIQUE,phone TEXT DEFAULT '', password_hash TEXT NOT NULL,role TEXT NOT NULL,restaurant_id INTEGER,status TEXT NOT NULL DEFAULT 'Ativo',created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS restaurants(id INTEGER PRIMARY KEY,name TEXT NOT NULL,owner TEXT NOT NULL,email TEXT NOT NULL,phone TEXT DEFAULT '',address TEXT DEFAULT '',status TEXT NOT NULL DEFAULT 'Pendente',created_at TEXT NOT NULL);
  CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY,restaurant_id INTEGER NOT NULL,name TEXT NOT NULL,category TEXT DEFAULT 'Geral',price REAL NOT NULL,description TEXT DEFAULT '',ingredients TEXT DEFAULT '',prep_minutes INTEGER DEFAULT 15,available INTEGER DEFAULT 1,FOREIGN KEY(restaurant_id) REFERENCES restaurants(id));
  CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY,restaurant_id INTEGER NOT NULL,customer_id INTEGER,customer TEXT NOT NULL,items_json TEXT NOT NULL,total REAL NOT NULL,status TEXT NOT NULL DEFAULT 'Aguardando',prep_minutes INTEGER DEFAULT 15,created_at TEXT NOT NULL,FOREIGN KEY(restaurant_id) REFERENCES restaurants(id));
  CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER NOT NULL,expires_at TEXT NOT NULL,FOREIGN KEY(user_id) REFERENCES users(id));
  CREATE TABLE IF NOT EXISTS stock(id INTEGER PRIMARY KEY,restaurant_id INTEGER NOT NULL,name TEXT,category TEXT,quantity REAL,minimum REAL,expiry TEXT DEFAULT '');
  CREATE TABLE IF NOT EXISTS stock_movements(id INTEGER PRIMARY KEY,restaurant_id INTEGER NOT NULL,stock_id INTEGER,kind TEXT,quantity REAL,note TEXT,created_at TEXT);
  CREATE TABLE IF NOT EXISTS employees(id INTEGER PRIMARY KEY,restaurant_id INTEGER NOT NULL,name TEXT,role TEXT,phone TEXT,shift TEXT,hire_date TEXT,status TEXT);
  CREATE TABLE IF NOT EXISTS payments(id INTEGER PRIMARY KEY,restaurant_id INTEGER NOT NULL,order_id INTEGER,customer TEXT,amount REAL,method TEXT,status TEXT,created_at TEXT);
  CREATE TABLE IF NOT EXISTS expenses(id INTEGER PRIMARY KEY,restaurant_id INTEGER NOT NULL,description TEXT,amount REAL,created_at TEXT);
  ''')
  # support account provisioned by environment, rotate password after first login
  support_email=os.getenv('MENUFLOW_SUPPORT_EMAIL','support@menuflow.local').lower()
  support_pw=os.getenv('MENUFLOW_SUPPORT_PASSWORD','ChangeMe-2026!')
  if not c.execute('SELECT id FROM users WHERE email=?',(support_email,)).fetchone():
   c.execute('INSERT INTO users(name,email,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?)',('MenuFlow Suporte',support_email,pw_hash(support_pw),'support','Ativo',now()))
init()

class Register(BaseModel): name:str; email:str; password:str=Field(min_length=8); phone:str=''
class RestaurantRequest(BaseModel): name:str; owner:str; email:str; password:str=Field(min_length=8); phone:str=''; address:str=''
class Login(BaseModel): email:str; password:str
class ProductIn(BaseModel): name:str; category:str='Geral'; price:float=Field(ge=0); description:str=''; ingredients:str=''; prep_minutes:int=15; available:bool=True
class OrderIn(BaseModel): items:list[dict]; customer_note:str=''; address:str=''; payment_method:str=''

def user_from(token):
 with db() as c:
  r=c.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires_at>?',(token,now())).fetchone()
 if not r: raise HTTPException(401,'Sessão inválida ou expirada. Entre novamente.')
 return dict(r)
def auth(authorization:str=Header(default='')):
 if not authorization.startswith('Bearer '): raise HTTPException(401,'Faça login para continuar')
 return user_from(authorization[7:])
def role(*roles):
 def dep(u=Depends(auth)):
  if u['role'] not in roles: raise HTTPException(403,'Sem permissão para esta área')
  if u['status']!='Ativo': raise HTTPException(403,'Conta suspensa ou pendente')
  return u
 return dep
def tenant(u):
 if u['role']!='restaurant' or not u['restaurant_id']: raise HTTPException(403,'Área exclusiva do restaurante')
 with db() as c:
  r=c.execute('SELECT * FROM restaurants WHERE id=? AND status="Aprovado"',(u['restaurant_id'],)).fetchone()
 if not r: raise HTTPException(403,'Restaurante ainda não aprovado ou suspenso')
 return dict(r)
def query(sql,p=()):
 with db() as c: return [dict(x) for x in c.execute(sql,p).fetchall()]

def create_session(uid):
 token=secrets.token_urlsafe(36)
 with db() as c: c.execute('INSERT INTO sessions VALUES(?,?,?)',(token,uid,(datetime.now()+timedelta(days=7)).isoformat(timespec='seconds')))
 return token

@app.get('/api/health')
def health(): return {'status':'ok','app':'MenuFlow'}
@app.post('/api/register/client')
def reg_client(p:Register):
 email=p.email.lower().strip()
 if not email: raise HTTPException(400,'E-mail obrigatório')
 try:
  with db() as c: cur=c.execute('INSERT INTO users(name,email,phone,password_hash,role,status,created_at) VALUES(?,?,?,?,?,?,?)',(p.name,email,p.phone,pw_hash(p.password),'client','Ativo',now()))
 except sqlite3.IntegrityError: raise HTTPException(409,'E-mail já cadastrado')
 return {'ok':True}
@app.post('/api/register/restaurant')
def reg_rest(p:RestaurantRequest):
 email=p.email.lower().strip()
 try:
  with db() as c:
   cur=c.execute('INSERT INTO restaurants(name,owner,email,phone,address,status,created_at) VALUES(?,?,?,?,?,?,?)',(p.name,p.owner,email,p.phone,p.address,'Pendente',now())); rid=cur.lastrowid
   c.execute('INSERT INTO users(name,email,phone,password_hash,role,restaurant_id,status,created_at) VALUES(?,?,?,?,?,?,?,?)',(p.owner,email,p.phone,pw_hash(p.password),'restaurant',rid,'Ativo',now()))
 except sqlite3.IntegrityError: raise HTTPException(409,'E-mail já cadastrado')
 return {'ok':True,'status':'Pendente'}
@app.post('/api/login')
def login(p:Login):
 with db() as c: r=c.execute('SELECT * FROM users WHERE email=?',(p.email.lower().strip(),)).fetchone()
 if not r or not verify(p.password,r['password_hash']): raise HTTPException(401,'E-mail ou senha inválidos')
 if r['status']!='Ativo': raise HTTPException(403,'Conta suspensa')
 if r['role']=='restaurant':
  with db() as c: rest=c.execute('SELECT status FROM restaurants WHERE id=?',(r['restaurant_id'],)).fetchone()
  if not rest or rest['status']!='Aprovado': raise HTTPException(403,'Cadastro do restaurante aguarda aprovação do suporte')
 token=create_session(r['id']); return {'token':token,'role':r['role'],'name':r['name'],'restaurant_id':r['restaurant_id']}
@app.post('/api/logout')
def logout(u=Depends(auth),authorization:str=Header(default='')):
 with db() as c:c.execute('DELETE FROM sessions WHERE token=?',(authorization[7:],))
 return {'ok':True}
@app.get('/api/client/restaurants')
def restaurants(u=Depends(role('client'))): return query('SELECT id,name,address FROM restaurants WHERE status="Aprovado" ORDER BY name')
@app.get('/api/client/restaurants/{rid}/products')
def client_products(rid:int,u=Depends(role('client'))):
 with db() as c:
  r=c.execute('SELECT id FROM restaurants WHERE id=? AND status="Aprovado"',(rid,)).fetchone()
  if not r: raise HTTPException(404,'Restaurante não encontrado')
  return [dict(x) for x in c.execute('SELECT id,name,category,price,description,ingredients,prep_minutes FROM products WHERE restaurant_id=? AND available=1 ORDER BY category,name',(rid,))]
@app.post('/api/client/restaurants/{rid}/orders')
def order_create(rid:int,p:OrderIn,u=Depends(role('client'))):
 if not p.items: raise HTTPException(400,'Selecione produtos')
 with db() as c:
  r=c.execute('SELECT id FROM restaurants WHERE id=? AND status="Aprovado"',(rid,)).fetchone()
  if not r: raise HTTPException(404,'Restaurante indisponível')
  total=0; parts=[]
  for item in p.items:
   prod=c.execute('SELECT id,name,price FROM products WHERE id=? AND restaurant_id=? AND available=1',(item.get('product_id'),rid)).fetchone()
   qty=int(item.get('quantity',0)); extras=str(item.get('extras','')); remove=str(item.get('remove',''))
   if not prod or qty<1 or qty>50: raise HTTPException(400,'Produto ou quantidade inválida')
   total+=prod['price']*qty; parts.append({'name':prod['name'],'quantity':qty,'unit_price':prod['price'],'extras':extras,'remove':remove})
  cur=c.execute('INSERT INTO orders(restaurant_id,customer_id,customer,items_json,total,status,prep_minutes,created_at) VALUES(?,?,?,?,?,?,?,?)',(rid,u['id'],u['name'],__import__('json').dumps({'items':parts,'note':p.customer_note,'address':p.address,'payment':p.payment_method},ensure_ascii=False),total,'Aguardando',15,now()))
 return {'ok':True,'order_id':cur.lastrowid,'total':total}
@app.get('/api/client/orders')
def my_orders(u=Depends(role('client'))): return query('SELECT id,restaurant_id,total,status,created_at,items_json FROM orders WHERE customer_id=? ORDER BY id DESC',(u['id'],))
# Platform support endpoints
@app.get('/api/support/restaurants')
def support_restaurants(u=Depends(role('support'))): return query('SELECT * FROM restaurants ORDER BY id DESC')
@app.patch('/api/support/restaurants/{rid}')
def support_status(rid:int,p:dict,u=Depends(role('support'))):
 status=p.get('status')
 if status not in ['Pendente','Aprovado','Suspenso']: raise HTTPException(400,'Status inválido')
 with db() as c: c.execute('UPDATE restaurants SET status=? WHERE id=?',(status,rid))
 return {'ok':True}
@app.get('/api/support/users')
def support_users(u=Depends(role('support'))): return query('SELECT id,name,email,role,status,created_at FROM users ORDER BY id DESC')
# restaurant admin endpoints, all data scoped by authenticated restaurant id
@app.get('/api/restaurant/products')
def r_products(u=Depends(role('restaurant'))):
 r=tenant(u); return query('SELECT * FROM products WHERE restaurant_id=? ORDER BY id DESC',(r['id'],))
@app.post('/api/restaurant/products')
def r_product_create(p:ProductIn,u=Depends(role('restaurant'))):
 r=tenant(u)
 with db() as c:cur=c.execute('INSERT INTO products(restaurant_id,name,category,price,description,ingredients,prep_minutes,available) VALUES(?,?,?,?,?,?,?,?)',(r['id'],p.name,p.category,p.price,p.description,p.ingredients,p.prep_minutes,int(p.available)))
 return {'id':cur.lastrowid,'ok':True}
@app.put('/api/restaurant/products/{pid}')
def r_product_edit(pid:int,p:ProductIn,u=Depends(role('restaurant'))):
 r=tenant(u)
 with db() as c:cur=c.execute('UPDATE products SET name=?,category=?,price=?,description=?,ingredients=?,prep_minutes=?,available=? WHERE id=? AND restaurant_id=?',(p.name,p.category,p.price,p.description,p.ingredients,p.prep_minutes,int(p.available),pid,r['id']))
 if not cur.rowcount:raise HTTPException(404,'Produto não encontrado')
 return {'ok':True}
@app.delete('/api/restaurant/products/{pid}')
def r_product_delete(pid:int,u=Depends(role('restaurant'))):
 r=tenant(u)
 with db() as c:cur=c.execute('DELETE FROM products WHERE id=? AND restaurant_id=?',(pid,r['id']))
 if not cur.rowcount:raise HTTPException(404,'Produto não encontrado')
 return {'ok':True}
@app.get('/api/restaurant/orders')
def r_orders(u=Depends(role('restaurant'))):
 r=tenant(u); return query('SELECT * FROM orders WHERE restaurant_id=? ORDER BY id DESC',(r['id'],))
@app.patch('/api/restaurant/orders/{oid}')
def r_order_status(oid:int,p:dict,u=Depends(role('restaurant'))):
 r=tenant(u);status=p.get('status')
 if status not in ['Aguardando','Em preparo','Pronto','Saiu para entrega','Concluído','Cancelado']:raise HTTPException(400,'Status inválido')
 with db() as c:cur=c.execute('UPDATE orders SET status=? WHERE id=? AND restaurant_id=?',(status,oid,r['id']))
 if not cur.rowcount:raise HTTPException(404,'Pedido não encontrado')
 return {'ok':True}
@app.get('/api/restaurant/summary')
def r_summary(u=Depends(role('restaurant'))):
 r=tenant(u);return {'products':len(query('SELECT id FROM products WHERE restaurant_id=?',(r['id'],))),'orders':len(query('SELECT id FROM orders WHERE restaurant_id=?',(r['id'],)))}
app.mount('/',StaticFiles(directory=ROOT/'frontend',html=True),name='frontend')
