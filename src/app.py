from flask import Flask, Response, request
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.exc import IntegrityError, DataError
from flask_restful import Resource, Api
import requests
from jsonschema import validate, ValidationError
from utils import MasonBuilder
import json
from bitmex_websocket import BitMEXWebsocket
from util.api_key import generate_nonce, generate_signature
from database import db, User, Orders
import traceback
from sqlalchemy.engine import Engine
from sqlalchemy import event

@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()

MASON = "application/vnd.mason+json"
app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///test.db"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
api = Api(app)
db.init_app(app)
with app.app_context():
    db.create_all()

class MasonControls(MasonBuilder):
    """ Based on the MasonControls class thas was used in Exercise 3
        Makes the response bodies and attaches Hypermedia controls to
        them. Also, holds the schemas for POST and PATCH methods.
    """

    @staticmethod
    def account_schema():
        """Schema of the account"""
        schema = {
            "type": "object",
            "required": ["accountname", "api_public", "api_secret"]
        }
        props = schema["properties"] = {}
        props["accountname"] = {
            "description": "name of the account",
            "type": "string"
        }
        props["api_public"] = {
            "description": "public part of the api-key",
            "type": "string"
        }

        props["api_secret"] = {
            "description": "secret part of the api-key",
            "type": "string"
        }
        return schema

    @staticmethod
    def order_schema():
        """Schema of the order"""
        schema = {
            "type": "object",
            "required": ["symbol", "size", "price", "side"]
        }
        props = schema["properties"] = {}
        props["symbol"] = {
            "description": "Order trading pair symbol",
            "type": "string"
        }
        props["size"] = {
            "description": "The size of the order in contract",
            "type": "integer"
        }

        props["price"] = {
            "description": "price of the order",
            "type": "number"
        }
        props["side"] = {
            "description": "side of the order",
            "type": "string"
        }
        return schema

    @staticmethod
    def position_schema():
        """ Schema for the position patch method """
        schema = {
            "type": "object",
            "required": ["leverage"]
        }
        props = schema["properties"] = {}
        props["leverage"] = {
            "description": "Leverage of the position",
            "type": "number"
        }
        return schema

    def add_control_accounts(self):
        """ adds accounts-all control to response body """
        self.add_control("accounts-all", href=api.url_for(Accounts),
                        method="GET",
                        title="List all the accounts registered")

    def add_control_account(self, apikey):
        """ adds account control to response body """
        self.add_control("account", href=api.url_for(Account, apikey=apikey),
                        method="GET",
                        title="Login to account")

    def add_control_orders(self, apikey):
        """ adds orders-all control to response body """
        self.add_control("orders-all", href=api.url_for(OrdersResource, apikey=apikey),
                        method="GET",
                        title="Get open orders")

    def add_control_orderbook(self):
        """ adds orderbook control to response body """
        self.add_control("orderbook", href=api.url_for(OrderBook),
                        method="GET",
                        title="Get order book data")

    def add_control_priceaction(self):
        """ adds priceaction control to response body """
        self.add_control("priceaction", href=api.url_for(PriceAction),
                        method="GET",
                        title="Show recent trades that happened in the market")

    def add_control_positions(self, apikey):
        """ adds positions-all control to response body """
        self.add_control("positions-all", href=api.url_for(Positions, apikey=apikey),
                        method="GET",
                        title="Get open positions")

    def add_control_accountbalance(self, apikey):
        """ adds balance control to response body """
        self.add_control("balance", href=api.url_for(AccountBalance, apikey=apikey),
                        method="GET",
                        title="Get account balance")

    def add_control_transactionhistory(self, apikey):
        """ adds transactions control to response body """
        self.add_control("transactions", href=api.url_for(TransactionHistory, apikey=apikey),
                        method="GET",
                        title="Get history of the wallet transactions")

    def add_control_add_account(self):
        """ adds add-account control to response body """
        self.add_control("add-account", href=api.url_for(Accounts),
                        method="POST",
                        encoding="json",
                        title="Add account to cryptotrading API",
                        schema=self.account_schema())

    def add_control_delete_account(self, apikey):
        """ adds delete control for deleting to response body """
        self.add_control("delete", href=api.url_for(Account, apikey=apikey),
                        method="DELETE",
                        title="delete this account")


    def add_control_add_order(self, apikey):
        """ adds add-order control to response body """
        self.add_control("add-order", href=api.url_for(OrdersResource, apikey=apikey),
                        method="POST",
                        encoding="json",
                        title="Add an order to Cryptotrading API",
                        schema=self.order_schema())

    def add_control_delete_order(self, apikey, orderid):
        """ adds delete control for deleting orders to response body """
        self.add_control("delete", href=api.url_for(OrderResource, apikey=apikey, orderid=orderid),
                        method="DELETE",
                        title="delete this order")



@app.route("/", methods=["GET"])
def entrypoint():
    """ This is the view function for the API entry point """
    body = MasonControls()
    body.add_control_accounts()
    body.add_control_orderbook() # resource is not implemented
    body.add_control_priceaction()
    return Response(json.dumps(body), status=200, mimetype=MASON)

class Accounts(Resource):
    def get(self):
        """ Lists all the accounts registered to cryptotrading api """
        userlist_q = User.query.all()
        userlist = []

        if len(userlist_q) == 0:  # if there are no accounts registered
            body = MasonControls(items=userlist)
            body.add_control("self", href=api.url_for(Accounts))
            body.add_control_add_account()
            return Response(json.dumps(body), status=200, mimetype=MASON)

        for user in userlist_q:
            userbody=MasonControls(accountname = user.username,
                                   api_public = user.api_public)
            userbody.add_control("self", href=api.url_for(Account, apikey=user.api_public), title="login to account")
            userlist.append(userbody)

        body = MasonControls(items=userlist)

        body.add_control_add_account()
        return Response(json.dumps(body), status=200, mimetype=MASON)

    def post(self):
        """ Makes new account to cryptotrading API. """
        if not request.json:
            return create_error_response(415, "Unsupported media type", "Requests must be JSON")
        try:
            validate(request.json, MasonControls.account_schema())
        except ValidationError as e:
            return create_error_response(400, "Invalid JSON document", str(e))

        user = User(username=request.json["accountname"],
                    api_public=request.json["api_public"],
                    api_secret=request.json["api_secret"])
        try:
            db.session.add(user)
            db.session.commit()

        except IntegrityError:
            return create_error_response(409, "Already exists",
                                        "Account with name '{}' already exists.".format(request.json["accountname"]))
        return Response(status=201, headers={"Location": api.url_for(Account, apikey=request.json["api_public"])})

class Account(Resource):
    def get(self, apikey):
        """ Sending get to Account resource logins to that account. """
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist", "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "need secret api-key in the http header")


        body = MasonControls(accountname=acc.username, api_public=acc.api_public, api_secret=acc.api_secret)
        body.add_control("self", api.url_for(Account, apikey=apikey))
        body.add_control_orders(apikey)
        body.add_control_accountbalance(apikey)
        body.add_control_positions(apikey)
        body.add_control_transactionhistory(apikey)
        body.add_control_delete_account(apikey)
        body.add_control_accounts()
        return Response(json.dumps(body), status=200, mimetype=MASON)

    def delete(self, apikey):
        """ Used for deleting the account """
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist", "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        db.session.delete(acc)
        db.session.commit()
        return Response(status=204)




def authorize(model, request):
    """ takes in user model and request object
        compares request object's api key to the saved api key in the database
    """
    try:
         secret = request.headers["api_secret"]
    except KeyError:
        return False
    if secret != model.api_secret:
        return False
    else:
        return True

class AccountBalance(Resource):
    """ Get Account Margin Balance from BitMEX Websocket API """
    def get(self, apikey):
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist",
             "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")


        ws = BitMEXWebsocket(endpoint="https://testnet.bitmex.com/api/v1", symbol="", api_key=acc.api_public, api_secret=request.headers["api_secret"])
        balance = ws.funds()

        body = MasonControls()
        body.add_control_account(apikey)
        body.add_control_transactionhistory(apikey)
        return Response(body, status=200, mimetype=MASON)

class TransactionHistory(Resource):
    """ not implemented """
    def get(self, apikey):
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist",
             "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        body = MasonControls()
        body.add_control_account(apikey)
        body.add_control_accountbalance(apikey)
        return Response(body, status=200, mimetype=MASON)

class OrdersResource(Resource):
    def get(self, apikey):
        """ lists the active orders made by the user """
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist",
             "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        # quries all the orders made by the account
        orderlist_q = Orders.query.filter_by(user_id=acc.id).all()
        orderlist = []

        if len(orderlist_q) == 0: # if there are no orders made by the account.
            body = MasonControls(items=orderlist)
            body.add_control_add_order(apikey)
            body.add_control("self", api.url_for(OrdersResource, apikey=apikey))
            body.add_control_account(apikey)
            return Response(json.dumps(body), status=200, mimetype=MASON)

        for order in orderlist_q:
            orderbody=MasonControls(id = order.order_id,
                                    price = order.order_price,
                                    symbol = order.order_symbol,
                                    side = order.order_side,
                                    size = order.order_size)
            orderbody.add_control("self", api.url_for(OrderResource, apikey=acc.api_public, orderid=order.order_id))
            # add maybe link to order profile
            orderlist.append(orderbody)

        body = MasonControls(items=orderlist)
        body.add_control_add_order(apikey)
        body.add_control("self", api.url_for(OrdersResource, apikey=apikey))
        body.add_control_account(apikey)
        return Response(json.dumps(body), status=200, mimetype=MASON)


    def post(self, apikey):
        """ posts new order to BitMEX test net and adds the order
            and its information to database.
        """
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist",
             "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        if not request.json:
            return create_error_response(415, "Unsupported media type", "Requests must be JSON")
        try:
            validate(request.json, MasonControls.order_schema())
        except ValidationError as e:
            return create_error_response(400, "Invalid JSON document", str(e))



        # post to bitmex websocket api
        # Receive order id with other data
        # add the order then to our own database
        url = '/api/v1/order'

        data = {"symbol" : request.json["symbol"],
                "orderQty" : request.json["size"],
                "price" : request.json["price"],
                "side" : request.json["side"]
        }

        headers = generate_headers(request.headers["api_secret"], acc.api_public, url, "POST", data)

        res = requests.post('https://testnet.bitmex.com' + url, json=data, headers=headers)
        # print(res.text)
        json_response = json.loads(res.text)
        order = Orders(order_id=json_response["orderID"],
                        order_size=json_response["orderQty"], order_side=json_response["side"],
                        order_symbol=json_response["symbol"], order_price=json_response["price"], user=acc)
        try:
            db.session.add(order)
            db.session.commit()

        except ValueError:
            return create_error_response(409, "Already exists", "")

        return Response(status=201, headers={"Location": api.url_for(OrderResource, apikey=apikey, orderid=json_response["orderID"])})

class OrderResource(Resource):
    def get(self, apikey, orderid):
        """ gets single order indetified by its url from the database """
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist",
             "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        order = Orders.query.filter_by(order_id=orderid).first()
        if not order:
               return create_error_response(404, "Order does not exist", "Order with orderid '{}' does not exist.".format(orderid))

        body = MasonControls(id = order.order_id,
                             price = order.order_price,
                             symbol = order.order_symbol,
                             side = order.order_side,
                             size = order.order_size)

        body.add_control("self", api.url_for(OrderResource, apikey=apikey, orderid=order.order_id))
        body.add_control_orders(apikey)
        body.add_control_delete_order(apikey, orderid)

        return Response(json.dumps(body), status=200, mimetype=MASON)

    def delete(self, apikey, orderid):
        """ deletes a single order from the BitMEX testnet
            and upon succesful deletion deletes the order from
            database.
        """
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist", "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        order = Orders.query.filter_by(order_id=orderid).first()
        if not order:
               return create_error_response(404, "Order does not exist", "Order with orderid '{}' does not exist.".format(orderid))

        # delete order in bitmex end
        url = '/api/v1/order'

        data = {"orderID" : orderid,
        }

        headers = generate_headers(request.headers["api_secret"], acc.api_public, url, "DELETE", data)

        res = requests.delete('https://testnet.bitmex.com' + url, json=data, headers=headers)



        # if everything works, and deletion is succesfful, continue

        db.session.delete(order)
        db.session.commit()
        return Response(status=204)

    def put(self, apikey, orderid):
        # not implemented
        return Response(status=503)

class OrderHistory(Resource):
    # not implemented
    def get(self):
        return Response(status=503)

class OrderBook(Resource):
    # not implemented
    def get(self):
        return Response(status=503)

class PriceAction(Resource):
    """ gets the most recent trade from the BitMEX
        needs symbol of the trade in query variable.
    """
    def get(self):
        if not request.args:
            return create_error_response(400, "Query Error", 'Missing Query Parameter "symbol"')
        try:
            if request.args["symbol"]:
                ws = BitMEXWebsocket(endpoint="https://testnet.bitmex.com/api/v1", symbol=request.args["symbol"], api_key=None, api_secret=None)
                trades = []
                trades = ws.recent_trades()
                for trade in trades:
                    body = MasonControls(symbol = trade["symbol"],
                                         side= trade["side"],
                                         size = trade["size"],
                                         price = trade["price"])
                    body.add_control("buckets", href=api.url_for(BucketedPriceAction) + "?{timebucket}",
                                     title="Trades in time buckets")
                    body.add_control("self", href=api.url_for(PriceAction) + "?symbol={}".format(trade["symbol"]))
                return Response(json.dumps(body), status=200, mimetype=MASON)
        except:
            print(traceback.format_exc())
            return create_error_response(400, "Query Error", "Query Parameter doesn't exist")

class BucketedPriceAction(Resource):
    # not implemented
    def get(self):
        return Response(status=503)

class Positions(Resource):
    """ Gets active positions from the BitMEX testnet """
    def get(self, apikey):
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist", "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        try:
            ws = BitMEXWebsocket(endpoint="https://testnet.bitmex.com/api/v1",
                                 symbol="", api_key=apikey,
                                 api_secret=request.headers["api_secret"])

            positions = []
            parsed_positions = []
            positions = ws.positions()
            ws.exit()
            if positions:
                for position in positions:

                    parsed_position_symbol = position["symbol"]
                    parsed_position_size = position["currentQty"]
                    if position["crossMargin"] == True:
                        parsed_position_leverage = 0
                    else:
                        parsed_position_leverage = position["leverage"]
                    parsed_position_entyprice = position["avgEntryPrice"]
                    parsed_position_liquidationPrice = position["liquidationPrice"]

                    parsed_position = MasonControls(symbol = parsed_position_symbol,
                                                    size = parsed_position_size,
                                                    leverage = parsed_position_leverage,
                                                    avgEntryPrice = parsed_position_entyprice,
                                                    liquidationPrice = parsed_position_liquidationPrice)
                    parsed_position.add_control("self", href=api.url_for(Position, apikey=apikey, symbol=parsed_position_symbol))
                    if not position["currentQty"] == 0:
                        parsed_positions.append(parsed_position)

            body = MasonControls(items=parsed_positions)
            body.add_control_account(apikey)
            body.add_control("self", api.url_for(Positions, apikey=apikey))
            return Response(json.dumps(body), status=200, mimetype=MASON)

        except TypeError:
            return create_error_response(400, "Query Error", "Query Parameter doesn't exist")


class Position(Resource):
    def get(self, apikey, symbol):
        """ Gets a single active position from the BitMEX testnet """
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist", "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        try:
            ws = BitMEXWebsocket(endpoint="https://testnet.bitmex.com/api/v1",
                                 symbol=symbol, api_key=apikey,
                                 api_secret=request.headers["api_secret"])

            positions = []
            parsed_positions = []
            positions = ws.positions()
            ws.exit()
            if positions:
                for position in positions:
                    parsed_position_symbol = position["symbol"]
                    parsed_position_size = position["currentQty"]
                    if position["crossMargin"] == True:
                        parsed_position_leverage = 0
                    else:
                        parsed_position_leverage = position["leverage"]
                    parsed_position_entyprice = position["avgEntryPrice"]
                    parsed_position_liquidationPrice = position["liquidationPrice"]

                    parsed_position = MasonControls(symbol = parsed_position_symbol,
                                                    size = parsed_position_size,
                                                    leverage = parsed_position_leverage,
                                                    avgEntryPrice = parsed_position_entyprice,
                                                    liquidationPrice = parsed_position_liquidationPrice)

                    parsed_position.add_control("self", href=api.url_for(Position, apikey=apikey, symbol=parsed_position_symbol))
                    parsed_position.add_control("edit", href=api.url_for(Position, apikey=apikey, symbol=parsed_position_symbol),
                                                method="PATCH",
                                                encoding="json",
                                                title="Change position leverage",
                                                schema=parsed_position.position_schema())

                    parsed_position.add_control_positions(apikey)
                    parsed_positions.append(parsed_position)

            if len(parsed_positions) == 1:
                body = parsed_positions[0]

                return Response(json.dumps(body), status=200, mimetype=MASON)
            else:
                return Response(json.dumps(parsed_positions), status=200, mimetype=MASON)
        except TypeError:
            return create_error_response(400, "Query Error", "Query Parameter doesn't exist")

    def patch(self, apikey, symbol):
        """ Edits active position's leverage attribute """
        acc = User.query.filter_by(api_public=apikey).first()
        if not acc:
            return create_error_response(404, "Account does not exist",
             "Account with api-key '{}' does not exist.".format(apikey))
        if not authorize(acc, request):
            return create_error_response(401, "Unauthorized", "No API-key or wrong API-key")

        if not request.json:
            return create_error_response(415, "Unsupported media type", "Requests must be JSON")
        try:
            validate(request.json, MasonControls.position_schema())
        except ValidationError as e:
            return create_error_response(400, "Invalid JSON document", str(e))

        try:

            data = {}
            data["symbol"] = symbol
            data["leverage"] = float(request.json["leverage"])

            url = '/api/v1/position/leverage'
            #Create signature and headers with BitMEXWebsocket generate signature function
            headers = generate_headers(request.headers["api_secret"], acc.api_public, url, "POST", data)

            res = requests.post('https://testnet.bitmex.com' + url, json=data, headers=headers)
            print(res.status_code)
            if res.status_code == 400:
                return create_error_response(400, "Parameter Error", "One of the parameters have an invalid value")
            return Response("", status=204, mimetype="application/json")
        except ValueError:
            return create_error_response(400, "Query Error", "Leverage must be a float value")




def generate_headers(api_secret, api_public, url, method, data):
    nonce = generate_nonce()
    headers = {
            "api-nonce" : str(nonce),
            "api-signature" :  generate_signature(api_secret, method, url, nonce, json.dumps(data)),
            "api-key" : api_public
        }
    return headers




""" routes for the resources """
api.add_resource(Accounts,"/accounts/")
api.add_resource(Account,"/accounts/<apikey>/")
api.add_resource(OrdersResource,"/accounts/<apikey>/orders/")
api.add_resource(OrderResource, "/accounts/<apikey>/orders/<orderid>/")
api.add_resource(PriceAction, "/priceaction/")
api.add_resource(Positions, "/accounts/<apikey>/positions/")
api.add_resource(Position, "/accounts/<apikey>/positions/<symbol>/")
api.add_resource(OrderBook, "/orderbook/")
api.add_resource(OrderHistory, "/accounts/<apikey>/orders/history/")
api.add_resource(TransactionHistory, "/accounts/<apikey>/history/")
api.add_resource(AccountBalance, "/accounts/<apikey>/balance/")
api.add_resource(BucketedPriceAction, "/priceaction/bucketed/")

def create_error_response(status_code, title, message=None):
    """ creates error responses using mason builder
        Based on the one used in Exercise 3 of the course.
    """
    resource_url = request.path
    body = MasonBuilder(resource_url=resource_url)
    body.add_error(title, message)
    # body.add_control("profile", href=ERROR_PROFILE)
    return Response(json.dumps(body), status_code, mimetype=MASON)
