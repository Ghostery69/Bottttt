from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import re
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Active CORS pour toutes les routes

# Initialisation de la base de données
def init_db():
    conn = sqlite3.connect('saveup_bf.db')
    c = conn.cursor()
    
    # Table des utilisateurs
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table des transactions
    c.execute('''
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL CHECK(type IN ('income', 'expense')),
            amount REAL NOT NULL CHECK(amount > 0),
            category TEXT NOT NULL,
            note TEXT,
            date TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Table des dépôts en attente
    c.execute('''
        CREATE TABLE IF NOT EXISTS pending_deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            source TEXT NOT NULL,
            note TEXT,
            date TIMESTAMP NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Table des demandes de retrait
    c.execute('''
        CREATE TABLE IF NOT EXISTS withdraw_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
            transaction_proof TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Table des demandes de dépôt Orange Money
    c.execute('''
        CREATE TABLE IF NOT EXISTS deposit_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_number TEXT NOT NULL,
            amount REAL NOT NULL CHECK(amount > 0),
            transaction_proof TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            processed_at TIMESTAMP
        )
    ''')
    
    conn.commit()
    conn.close()

# Vérification du format du numéro de téléphone
def is_valid_phone_number(phone_number):
    pattern = r'^\+?226\d{8}$'  # Format Burkinabé: +226XXXXXXXX ou 226XXXXXXXX
    return re.match(pattern, phone_number) is not None

# Récupérer l'ID utilisateur à partir du numéro de téléphone
def get_user_id(phone_number):
    conn = sqlite3.connect('saveup_bf.db')
    c = conn.cursor()
    c.execute("SELECT id FROM users WHERE phone_number = ?", (phone_number,))
    result = c.fetchone()
    conn.close()
    return result[0] if result else None

# Appliquer les dépôts en attente pour un utilisateur
def apply_pending_deposits(user_id, phone_number):
    conn = sqlite3.connect('saveup_bf.db')
    c = conn.cursor()
    
    # Récupérer les dépôts en attente
    c.execute("SELECT * FROM pending_deposits WHERE phone_number = ?", (phone_number,))
    pending_deposits = c.fetchall()
    
    if pending_deposits:
        # Ajouter chaque dépôt en attente comme revenu
        for deposit in pending_deposits:
            c.execute(
                "INSERT INTO transactions (user_id, type, amount, category, note, date) VALUES (?, 'income', ?, ?, ?, ?)",
                (user_id, deposit[2], deposit[3], deposit[4], deposit[5])
            )
        
        # Supprimer les dépôts en attente après les avoir appliqués
        c.execute("DELETE FROM pending_deposits WHERE phone_number = ?", (phone_number,))
        conn.commit()
    
    conn.close()
    return len(pending_deposits)

@app.route('/create_user', methods=['POST'])
def create_user():
    data = request.get_json()
    
    phone_number = data.get('phone_number')
    name = data.get('name')
    
    # Validation des données
    if not phone_number or not name:
        return jsonify({
            'status': 'error',
            'message': 'Le numéro de téléphone et le nom sont requis'
        }), 400
    
    if not is_valid_phone_number(phone_number):
        return jsonify({
            'status': 'error',
            'message': 'Format de numéro de téléphone invalide. Utilisez le format: +226XXXXXXXX ou 226XXXXXXXX'
        }), 400
    
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        # Vérifier si l'utilisateur existe déjà
        c.execute("SELECT id FROM users WHERE phone_number = ?", (phone_number,))
        if c.fetchone():
            return jsonify({
                'status': 'error',
                'message': 'Un utilisateur avec ce numéro de téléphone existe déjà'
            }), 400
        
        # Créer l'utilisateur
        c.execute(
            "INSERT INTO users (phone_number, name) VALUES (?, ?)",
            (phone_number, name)
        )
        user_id = c.lastrowid
        
        # Appliquer les dépôts en attente s'il y en a
        pending_count = apply_pending_deposits(user_id, phone_number)
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': f'Utilisateur créé avec succès. {pending_count} dépôt(s) en attente ont été crédités.',
            'data': {
                'user_id': user_id,
                'phone_number': phone_number,
                'name': name
            }
        }), 201
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de la création de l\'utilisateur: {str(e)}'
        }), 500

@app.route('/add_income', methods=['POST'])
def add_income():
    data = request.get_json()
    
    phone_number = data.get('phone_number')
    amount = data.get('amount')
    source = data.get('source')
    note = data.get('note', '')
    date_str = data.get('date')
    
    # Validation des données
    if not phone_number or not amount or not source:
        return jsonify({
            'status': 'error',
            'message': 'Le numéro de téléphone, le montant et la source sont requis'
        }), 400
    
    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({
                'status': 'error',
                'message': 'Le montant doit être positif'
            }), 400
    except ValueError:
        return jsonify({
            'status': 'error',
            'message': 'Le montant doit être un nombre valide'
        }), 400
    
    # Traitement de la date
    if date_str:
        try:
            date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({
                'status': 'error',
                'message': 'Format de date invalide. Utilisez le format ISO (YYYY-MM-DD)'
            }), 400
    else:
        date = datetime.now()
    
    try:
        user_id = get_user_id(phone_number)
        
        if user_id:
            # L'utilisateur existe, ajouter la transaction
            conn = sqlite3.connect('saveup_bf.db')
            c = conn.cursor()
            
            c.execute(
                "INSERT INTO transactions (user_id, type, amount, category, note, date) VALUES (?, 'income', ?, ?, ?, ?)",
                (user_id, amount, source, note, date)
            )
            
            conn.commit()
            conn.close()
            
            return jsonify({
                'status': 'success',
                'message': 'Revenu ajouté avec succès'
            }), 201
        else:
            # L'utilisateur n'existe pas, stocker le dépôt en attente
            conn = sqlite3.connect('saveup_bf.db')
            c = conn.cursor()
            
            c.execute(
                "INSERT INTO pending_deposits (phone_number, amount, source, note, date) VALUES (?, ?, ?, ?, ?)",
                (phone_number, amount, source, note, date)
            )
            
            conn.commit()
            conn.close()
            
            return jsonify({
                'status': 'success',
                'message': 'Dépôt en attente créé. Il sera crédité lorsque l\'utilisateur créera un compte.'
            }), 201
            
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de l\'ajout du revenu: {str(e)}'
        }), 500

@app.route('/add_expense', methods=['POST'])
def add_expense():
    data = request.get_json()
    
    phone_number = data.get('phone_number')
    amount = data.get('amount')
    category = data.get('category')
    note = data.get('note', '')
    date_str = data.get('date')
    
    # Validation des données
    if not phone_number or not amount or not category:
        return jsonify({
            'status': 'error',
            'message': 'Le numéro de téléphone, le montant et la catégorie sont requis'
        }), 400
    
    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({
                'status': 'error',
                'message': 'Le montant doit être positif'
            }), 400
    except ValueError:
        return jsonify({
            'status': 'error',
            'message': 'Le montant doit être un nombre valide'
        }), 400
    
    # Vérifier que l'utilisateur existe
    user_id = get_user_id(phone_number)
    if not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Aucun utilisateur trouvé avec ce numéro de téléphone'
        }), 404
    
    # Traitement de la date
    if date_str:
        try:
            date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({
                'status': 'error',
                'message': 'Format de date invalide. Utilisez le format ISO (YYYY-MM-DD)'
            }), 400
    else:
        date = datetime.now()
    
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        c.execute(
            "INSERT INTO transactions (user_id, type, amount, category, note, date) VALUES (?, 'expense', ?, ?, ?, ?)",
            (user_id, amount, category, note, date)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Dépense ajoutée avec succès'
        }), 201
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de l\'ajout de la dépense: {str(e)}'
        }), 500

@app.route('/get_balance/<phone_number>', methods=['GET'])
def get_balance(phone_number):
    # Vérifier que l'utilisateur existe
    user_id = get_user_id(phone_number)
    if not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Aucun utilisateur trouvé avec ce numéro de téléphone'
        }), 404
    
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        # Calculer le solde
        c.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) as balance
            FROM transactions 
            WHERE user_id = ?
        """, (user_id,))
        balance = c.fetchone()[0]
        
        # Récupérer les transactions
        c.execute("""
            SELECT type, amount, category, note, date 
            FROM transactions 
            WHERE user_id = ? 
            ORDER BY date DESC
        """, (user_id,))
        
        transactions = []
        for row in c.fetchall():
            transactions.append({
                'type': row[0],
                'amount': row[1],
                'category': row[2],
                'note': row[3],
                'date': row[4]
            })
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'data': {
                'balance': balance,
                'transactions': transactions
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de la récupération du solde: {str(e)}'
        }), 500

@app.route('/pending_deposits/<phone_number>', methods=['GET'])
def get_pending_deposits(phone_number):
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        c.execute("SELECT amount, source, note, date FROM pending_deposits WHERE phone_number = ?", (phone_number,))
        
        deposits = []
        for row in c.fetchall():
            deposits.append({
                'amount': row[0],
                'source': row[1],
                'note': row[2],
                'date': row[3]
            })
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'data': {
                'pending_deposits': deposits,
                'count': len(deposits)
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de la récupération des dépôts en attente: {str(e)}'
        }), 500

# Demande de dépôt Orange Money
@app.route('/request_deposit', methods=['POST'])
def request_deposit():
    data = request.get_json()
    
    phone_number = data.get('phone_number')
    amount = data.get('amount')
    transaction_proof = data.get('transaction_proof')
    
    # Validation des données
    if not phone_number or not amount or not transaction_proof:
        return jsonify({
            'status': 'error',
            'message': 'Le numéro de téléphone, le montant et la preuve de transaction sont requis'
        }), 400
    
    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({
                'status': 'error',
                'message': 'Le montant doit être positif'
            }), 400
    except ValueError:
        return jsonify({
            'status': 'error',
            'message': 'Le montant doit être un nombre valide'
        }), 400
    
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        # Créer la demande de dépôt
        c.execute(
            "INSERT INTO deposit_requests (phone_number, amount, transaction_proof) VALUES (?, ?, ?)",
            (phone_number, amount, transaction_proof)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Demande de dépôt envoyée avec succès. Elle sera traitée par un administrateur.'
        }), 201
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de la demande de dépôt: {str(e)}'
        }), 500

# Demande de retrait
@app.route('/request_withdraw', methods=['POST'])
def request_withdraw():
    data = request.get_json()
    
    phone_number = data.get('phone_number')
    amount = data.get('amount')
    transaction_proof = data.get('transaction_proof', '')
    
    # Validation des données
    if not phone_number or not amount:
        return jsonify({
            'status': 'error',
            'message': 'Le numéro de téléphone et le montant sont requis'
        }), 400
    
    try:
        amount = float(amount)
        if amount <= 0:
            return jsonify({
                'status': 'error',
                'message': 'Le montant doit être positif'
            }), 400
    except ValueError:
        return jsonify({
            'status': 'error',
            'message': 'Le montant doit être un nombre valide'
        }), 400
    
    # Vérifier que l'utilisateur existe
    user_id = get_user_id(phone_number)
    if not user_id:
        return jsonify({
            'status': 'error',
            'message': 'Aucun utilisateur trouvé avec ce numéro de téléphone'
        }), 404
    
    # Vérifier que le solde est suffisant
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        c.execute("""
            SELECT 
                COALESCE(SUM(CASE WHEN type = 'income' THEN amount ELSE 0 END), 0) -
                COALESCE(SUM(CASE WHEN type = 'expense' THEN amount ELSE 0 END), 0) as balance
            FROM transactions 
            WHERE user_id = ?
        """, (user_id,))
        balance = c.fetchone()[0]
        
        if balance < amount:
            return jsonify({
                'status': 'error',
                'message': 'Solde insuffisant pour effectuer ce retrait'
            }), 400
        
        # Créer la demande de retrait
        c.execute(
            "INSERT INTO withdraw_requests (user_id, amount, transaction_proof) VALUES (?, ?, ?)",
            (user_id, amount, transaction_proof)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Demande de retrait envoyée avec succès. Elle sera traitée par un administrateur.'
        }), 201
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de la demande de retrait: {str(e)}'
        }), 500

# Endpoints d'administration

# Voir toutes les demandes de dépôt
@app.route('/admin/deposits', methods=['GET'])
def admin_get_deposits():
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        c.execute("""
            SELECT dr.id, dr.phone_number, dr.amount, dr.transaction_proof, dr.status, dr.created_at, dr.processed_at, u.name
            FROM deposit_requests dr
            LEFT JOIN users u ON dr.phone_number = u.phone_number
            ORDER BY dr.created_at DESC
        """)
        
        deposits = []
        for row in c.fetchall():
            deposits.append({
                'id': row[0],
                'phone_number': row[1],
                'amount': row[2],
                'transaction_proof': row[3],
                'status': row[4],
                'created_at': row[5],
                'processed_at': row[6],
                'user_name': row[7] or 'Utilisateur non enregistré'
            })
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'data': {
                'deposits': deposits,
                'count': len(deposits)
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de la récupération des demandes de dépôt: {str(e)}'
        }), 500

# Voir toutes les demandes de retrait
@app.route('/admin/withdraws', methods=['GET'])
def admin_get_withdraws():
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        c.execute("""
            SELECT wr.id, u.phone_number, u.name, wr.amount, wr.transaction_proof, wr.status, wr.created_at, wr.processed_at
            FROM withdraw_requests wr
            JOIN users u ON wr.user_id = u.id
            ORDER BY wr.created_at DESC
        """)
        
        withdraws = []
        for row in c.fetchall():
            withdraws.append({
                'id': row[0],
                'phone_number': row[1],
                'user_name': row[2],
                'amount': row[3],
                'transaction_proof': row[4],
                'status': row[5],
                'created_at': row[6],
                'processed_at': row[7]
            })
        
        conn.close()
        
        return jsonify({
            'status': 'success',
            'data': {
                'withdraws': withdraws,
                'count': len(withdraws)
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de la récupération des demandes de retrait: {str(e)}'
        }), 500

# Approuver un dépôt
@app.route('/admin/approve_deposit/<int:deposit_id>', methods=['POST'])
def admin_approve_deposit(deposit_id):
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        # Récupérer les informations de la demande
        c.execute("SELECT phone_number, amount FROM deposit_requests WHERE id = ?", (deposit_id,))
        deposit = c.fetchone()
        
        if not deposit:
            return jsonify({
                'status': 'error',
                'message': 'Demande de dépôt non trouvée'
            }), 404
        
        phone_number, amount = deposit
        
        # Vérifier si l'utilisateur existe
        user_id = get_user_id(phone_number)
        
        if user_id:
            # Créditer le compte de l'utilisateur
            c.execute(
                "INSERT INTO transactions (user_id, type, amount, category, note, date) VALUES (?, 'income', ?, 'Dépôt Orange Money', 'Dépôt approuvé par administrateur', ?)",
                (user_id, amount, datetime.now())
            )
        else:
            # Stocker en attente si l'utilisateur n'existe pas encore
            c.execute(
                "INSERT INTO pending_deposits (phone_number, amount, source, note, date) VALUES (?, ?, 'Dépôt Orange Money', 'Dépôt approuvé par administrateur', ?)",
                (phone_number, amount, datetime.now())
            )
        
        # Mettre à jour le statut de la demande
        c.execute(
            "UPDATE deposit_requests SET status = 'approved', processed_at = ? WHERE id = ?",
            (datetime.now(), deposit_id)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Dépôt approuvé et compte crédité avec succès'
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de l\'approbation du dépôt: {str(e)}'
        }), 500

# Rejeter un dépôt
@app.route('/admin/reject_deposit/<int:deposit_id>', methods=['POST'])
def admin_reject_deposit(deposit_id):
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        # Mettre à jour le statut de la demande
        c.execute(
            "UPDATE deposit_requests SET status = 'rejected', processed_at = ? WHERE id = ?",
            (datetime.now(), deposit_id)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Dépôt rejeté avec succès'
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors du rejet du dépôt: {str(e)}'
        }), 500

# Approuver un retrait
@app.route('/admin/approve_withdraw/<int:withdraw_id>', methods=['POST'])
def admin_approve_withdraw(withdraw_id):
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        # Récupérer les informations de la demande
        c.execute("SELECT user_id, amount FROM withdraw_requests WHERE id = ?", (withdraw_id,))
        withdraw = c.fetchone()
        
        if not withdraw:
            return jsonify({
                'status': 'error',
                'message': 'Demande de retrait non trouvée'
            }), 404
        
        user_id, amount = withdraw
        
        # Débiter le compte de l'utilisateur
        c.execute(
            "INSERT INTO transactions (user_id, type, amount, category, note, date) VALUES (?, 'expense', ?, 'Retrait', 'Retrait approuvé par administrateur', ?)",
            (user_id, amount, datetime.now())
        )
        
        # Mettre à jour le statut de la demande
        c.execute(
            "UPDATE withdraw_requests SET status = 'approved', processed_at = ? WHERE id = ?",
            (datetime.now(), withdraw_id)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Retrait approuvé et compte débité avec succès'
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors de l\'approbation du retrait: {str(e)}'
        }), 500

# Rejeter un retrait
@app.route('/admin/reject_withdraw/<int:withdraw_id>', methods=['POST'])
def admin_reject_withdraw(withdraw_id):
    try:
        conn = sqlite3.connect('saveup_bf.db')
        c = conn.cursor()
        
        # Mettre à jour le statut de la demande
        c.execute(
            "UPDATE withdraw_requests SET status = 'rejected', processed_at = ? WHERE id = ?",
            (datetime.now(), withdraw_id)
        )
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'status': 'success',
            'message': 'Retrait rejeté avec succès'
        }), 200
        
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'Erreur lors du rejet du retrait: {str(e)}'
        }), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
