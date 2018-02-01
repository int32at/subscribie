import os
from os import environ
from os.path import join, dirname
import time
from subprocess import Popen, PIPE
import datetime
import urlparse
import requests
import werkzeug
from werkzeug.wrappers import Request, Response
from werkzeug.routing import Map, Rule
from werkzeug.exceptions import HTTPException, NotFound, default_exceptions
from werkzeug.wsgi import SharedDataMiddleware
from werkzeug.utils import redirect
from jinja2 import Environment, FileSystemLoader
from werkzeug.contrib.sessions import SessionMiddleware, \
          FilesystemSessionStore
from bs4 import BeautifulSoup
import gocardless_pro
import sqlite3
import smtplib
from penguin_rest import Rest
import sendgrid
from sendgrid.helpers.mail import *

class Shortly(object):
    session_store = FilesystemSessionStore()

    def __init__(self, config):
        source("./.env")
        self.gocclient = gocardless_pro.Client(
            access_token = os.getenv('gocardless_token'),
            environment= os.getenv('gocardless_environment')
        )
        template_path = os.path.join(os.path.dirname(__file__), 'templates')
        self.jinja_env = Environment(loader=FileSystemLoader(template_path),
                                     autoescape=True)
        self.url_map = Map([
            Rule('/', endpoint='start'),
            Rule('/broadband-availability-postcode-checker', endpoint='broadband_availability_postcode_checker'),
            Rule('/sign', endpoint='sign'),
            Rule('/new_customer', endpoint='new_customer'),
            Rule('/establish_mandate', endpoint='establish_mandate'),
            Rule('/complete_mandate', endpoint='complete_mandate'),
            Rule('/thankyou', endpoint='thankyou'),
            Rule('/test', endpoint='test'),
            Rule('/gettingstarted', endpoint='gettingstarted'),
            Rule('/prerequisites', endpoint='prerequisites'),
            Rule('/manifest.json', endpoint='manifest'),
            Rule('/app.js', endpoint='appjs'),
            Rule('/sw.js', endpoint='sw')
        ])

    #####################
    #   Error Routes
    #####################

    def on_appjs(self, template_name, **context):
        return Response(file('app.js'), direct_passthrough=True, mimetype='application/javascript')

    def on_manifest(self, template_name, **context):
        return Response(file('manifest.json'), direct_passthrough=True, mimetype='application/json')

    def on_sw(self, template_name, **context):
        return Response(file('sw.js'), direct_passthrough=True, mimetype='application/javascript')

    def render_template(self, template_name, **context):
        t = self.jinja_env.get_template(template_name)
        return Response(t.render(context), mimetype='text/html')

    def on_sign(self,request):
        return self.render_template('signature.html')

    def on_thankyou(self, request):
        return self.render_template('thankyou.html')

    def on_test(self, request):

        sid = "7a924ff4030a765278ed2da95000da67fbcdd75e"
        con = sqlite3.connect(os.getenv('db_full_path'))
        cur = con.cursor()
        cur.execute("SELECT * FROM person WHERE sid = ?", (sid,))
        row = cur.fetchone()
        customerName = row[2] + " " + row[3]
        customerAddress = row[4] + ", " + row[5] + ", " + row[6]
        customerEmail = row[7]
        customerPhone = row[8]
        broadbandPackage = row[9]
        customerExistingLine = row[10]
        customerExistingNumber = row[11]

        currentDate = datetime.datetime.now()
        goLive = currentDate + datetime.timedelta(days = 15)

        if broadbandPackage == "adsl":
            broadbandPackage = "ADSL 2+"
            contractExpiry = goLive + datetime.timedelta(days = 90)
            monthlyCost = "34.99"
        elif broadbandPackage == "fibre":
            broadbandPackage = "FTTC 40:10"
            contractExpiry = goLive + datetime.timedelta(days = 365)
            monthlyCost = "41.99"
        elif broadbandPackage == "fibre_plus":
            broadbandPackage = "FTTC 80:20"
            contractExpiry = goLive + datetime.timedelta(days = 365)
            monthlyCost = "41.99"

        contractExpiry = contractExpiry.strftime('%d/%m/%Y') + "*"
        goLive = goLive.strftime('%d/%m/%Y')

        ## ADMIN
        sg = sendgrid.SendGridAPIClient(apikey=os.environ.get('SENDGRID_API_KEY'))
        from_email = Email("broadband@karmacomputing.co.uk", "BB ORDER")
        to_email = Email("broadband@karmacomputing.co.uk")
        subject = "NEW BROABDAND ORDER"
        content = Content("text/html", "There has been an error constructing this email.")
        mail = Mail(from_email, subject, to_email, content)
        mail.personalizations[0].add_substitution(Substitution("-customerName-", customerName))
        mail.personalizations[0].add_substitution(Substitution("-customerPhone-", customerPhone))
        mail.personalizations[0].add_substitution(Substitution("-customerAddress-", customerAddress))
        mail.personalizations[0].add_substitution(Substitution("-customerEmail-", customerEmail))
        mail.personalizations[0].add_substitution(Substitution("-broadbandPackage-", broadbandPackage))
        mail.personalizations[0].add_substitution(Substitution("-customerExistingLine-", customerExistingLine))
        mail.personalizations[0].add_substitution(Substitution("-customerExistingNumber-", customerExistingNumber))
        mail.template_id = "8b49f623-9368-4cf6-94c1-53cc2f429b9b"
        try:
            response = sg.client.mail.send.post(request_body=mail.get())
        except urllib.HTTPError as e:
            print (e.read())
            exit()
        print(response.status_code)
        print(response.body)
        print(response.headers)

        ## CUSTOMER
        from_email = Email("broadband@karmacomputing.co.uk", "Karma Broadband Team")
        to_email = Email(customerEmail)
        mail = Mail(from_email, subject, to_email, content)
        mail.personalizations[0].add_substitution(Substitution("-customerName-", customerName))
        mail.personalizations[0].add_substitution(Substitution("-package-", broadbandPackage))
        mail.personalizations[0].add_substitution(Substitution("-contractExpiry-", contractExpiry))
        mail.personalizations[0].add_substitution(Substitution("-goLive-", goLive))
        mail.personalizations[0].add_substitution(Substitution("-monthlyCost-", monthlyCost))
        mail.template_id = "0c383660-2801-4448-b3cf-9bb608de9ec7"
        try:
            response = sg.client.mail.send.post(request_body=mail.get())
        except urllib.HTTPError as e:
            print (e.read())
            exit()
        print(response.status_code)
        print(response.body)
        print(response.headers)

        return self.render_template('thankyou.html')

    def on_gettingstarted(self, request):
        return self.render_template('gettingstarted.html')

    def on_prerequisites(self, request):
        """
        Render template with mandatory questions for a
        sucessful onboarding e.g. "Do you already have
        a x,y,z?".
        """
        return self.render_template('prerequisites.html')

    def on_broadband_availability_postcode_checker(self,request):
        return self.render_template('broadband-availability-postcode-checker.html')

    def on_new_customer(self, request):
        if request.method == 'POST':
            given_name = request.form['given_name']
            family_name = request.form['family_name']
            address_line1 = request.form['address_line1']
            city = request.form['city']
            postal_code = request.form['postal_code']
            email = request.form['email']
            mobile = request.form['mobile']
            now = datetime.datetime.now()
            wants = request.args.get('plan')
            # Store customer
            sid = request.cookies.get('karma_cookie')
            con = sqlite3.connect(os.getenv("db_full_path"))
            cur = con.cursor()
            cur.execute("INSERT INTO person VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", (sid, now, given_name, family_name, address_line1, city, postal_code, email, mobile, wants, 'null', 'null', False))
            con.commit()
            cur.execute("SELECT * FROM person")
            print cur.fetchone()
            con.close()

            #redirect to Crab with sid in the query
            return redirect(os.getenv('crab_url') + '?sid=' + sid + '&package=' + wants + '&fname=' + given_name)
            #return redirect(os.getenv('establish_mandate_url'))

        #GET request
        else:
            package = request.args["plan"]
            return self.render_template('new_customer.html', package=package)

    def on_establish_mandate(self, request):
        #lookup the customer with sid and get their relevant details
        sid = request.cookies.get('karma_cookie')
        con = sqlite3.connect(os.getenv("db_full_path"))
        cur = con.cursor()
        cur.execute("SELECT * FROM person p WHERE p.sid = ?", (sid,))
        res = cur.fetchone()
        print res
        con.close()

        if res:
            # validate that hasInstantPaid is true for the customer
            if res[12] == True:
                redirect_flow = self.gocclient.redirect_flows.create(
                    params = {
                        "description" : "Karma Computing Broadband",
                        "session_token" : sid,
                        "success_redirect_url" : os.getenv('success_redirect_url'),
                        "prefilled_customer" : {
                            "given_name" : res[2],
                            "family_name": res[3],
                            "address_line1": res[4],
                            "city" : res[5],
                            "postal_code": res[6],
                            "email": res[7]
                        }
                    }
                )
                # Hold on to this ID - we'll need it when we
                # "confirm" the dedirect flow later
                print("ID: {} ".format(redirect_flow.id))
                print("URL: {} ".format(redirect_flow.redirect_url))
                return redirect(redirect_flow.redirect_url)
            else:
                print "hasInstantPaid on this customer was false"
                #TODO: respond with 403
        else:
            print "no customer found with sid"
            #TODO: respond with 400

    def on_complete_mandate(self, request):
        redirect_flow_id = request.args.get('redirect_flow_id')
        print("Recieved flow ID: {} ".format(redirect_flow_id))

        redirect_flow = self.gocclient.redirect_flows.complete(
            redirect_flow_id,
            params = {
                "session_token": request.cookies.get('karma_cookie')
        })
        print ("Mandate: {}".format(redirect_flow.links.mandate))
        # Save this mandate ID for the next section.
        print ("Customer: {}".format(redirect_flow.links.customer))

        # Store customer
        sid = request.cookies.get('karma_cookie')
        now = datetime.datetime.now()
        mandate = redirect_flow.links.mandate
        customer = redirect_flow.links.customer
        flow = redirect_flow_id

        con = sqlite3.connect(os.getenv('db_full_path'))
        cur = con.cursor()
        cur.execute("SELECT * FROM person WHERE sid = ?", (sid,))
        row = cur.fetchone()
        customerName = row[2] + " " + row[3]
        customerAddress = row[4] + ", " + row[5] + ", " + row[6]
        customerEmail = row[7]
        customerPhone = row[8]
        broadbandPackage = row[9]
        customerExistingLine = row[10]
        customerExistingNumber = row[11]

        currentDate = datetime.datetime.now()
        goLive = currentDate + datetime.timedelta(days = 15)

        if broadbandPackage == "adsl":
            broadbandPackage = "ADSL 2+"
            contractExpiry = goLive + datetime.timedelta(days = 90)
            monthlyCost = "34.99"
        elif broadbandPackage == "fibre":
            broadbandPackage = "FTTC 40:10"
            contractExpiry = goLive + datetime.timedelta(days = 365)
            monthlyCost = "41.99"
        elif broadbandPackage == "fibre_plus":
            broadbandPackage = "FTTC 80:20"
            contractExpiry = goLive + datetime.timedelta(days = 365)
            monthlyCost = "41.99"

        contractExpiry = contractExpiry.strftime('%d/%m/%Y') + "*"
        goLive = goLive.strftime('%d/%m/%Y')

        ## ADMIN
        sg = sendgrid.SendGridAPIClient(apikey=os.environ.get('SENDGRID_API_KEY'))
        from_email = Email("broadband@karmacomputing.co.uk", "BB ORDER")
        to_email = Email("broadband@karmacomputing.co.uk")
        subject = "NEW BROABDAND ORDER"
        content = Content("text/html", "There has been an error constructing this email.")
        mail = Mail(from_email, subject, to_email, content)
        mail.personalizations[0].add_substitution(Substitution("-customerName-", customerName))
        mail.personalizations[0].add_substitution(Substitution("-customerPhone-", customerPhone))
        mail.personalizations[0].add_substitution(Substitution("-customerAddress-", customerAddress))
        mail.personalizations[0].add_substitution(Substitution("-customerEmail-", customerEmail))
        mail.personalizations[0].add_substitution(Substitution("-broadbandPackage-", broadbandPackage))
        mail.personalizations[0].add_substitution(Substitution("-customerExistingLine-", customerExistingLine))
        mail.personalizations[0].add_substitution(Substitution("-customerExistingNumber-", customerExistingNumber))
        mail.template_id = "8b49f623-9368-4cf6-94c1-53cc2f429b9b"
        try:
            response = sg.client.mail.send.post(request_body=mail.get())
        except urllib.HTTPError as e:
            print (e.read())
            exit()
        print(response.status_code)
        print(response.body)
        print(response.headers)

        ## CUSTOMER
        from_email = Email("broadband@karmacomputing.co.uk", "Karma Broadband Team")
        to_email = Email(customerEmail)
        mail = Mail(from_email, subject, to_email, content)
        mail.personalizations[0].add_substitution(Substitution("-customerName-", customerName))
        mail.personalizations[0].add_substitution(Substitution("-package-", broadbandPackage))
        mail.personalizations[0].add_substitution(Substitution("-contractExpiry-", contractExpiry))
        mail.personalizations[0].add_substitution(Substitution("-goLive-", goLive))
        mail.personalizations[0].add_substitution(Substitution("-monthlyCost-", monthlyCost))
        mail.template_id = "0c383660-2801-4448-b3cf-9bb608de9ec7"
        try:
            response = sg.client.mail.send.post(request_body=mail.get())
        except urllib.HTTPError as e:
            print (e.read())
            exit()
        print(response.status_code)
        print(response.body)
        print(response.headers)

        # Display a confirmation page to the customer, telling them
        # their Direct Debit has been set up. You could build your own,
        # or use ours, which shows all the relevant information and is
        # translated into all the languages we support.
        print("Confirmation URL: {}".format(redirect_flow.confirmation_url))
        return redirect(os.getenv('thankyou_url'))

    def on_start(self,request):
        error = None
        nophone = False
        try:
            if 'nophone' in request.headers['Cookie']:
                nophone=True
        except  KeyError:
            pass
        result = ''
        if request.method == 'POST':
            print(os.getenv('db_full_path'))
            buildingnumber = request.form['buildingnumber']
            PostCode = request.form['PostCode']
            now = datetime.datetime.now()
            prettyTime = datetime.datetime.now().strftime("%H:%M %D")
            sid = request.cookies.get('karma_cookie')
            con = sqlite3.connect(os.getenv('db_full_path'))
            cur = con.cursor()
            cur.execute("INSERT INTO lookups VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (sid, now, buildingnumber, '', '', '', '', PostCode))
            con.commit()
            cur.execute("SELECT * FROM lookups")
            print cur.fetchone()
            con.close()
            canADSL = False
            canFibre = False
            if not is_valid_lookup(request.form):
                error = 'Please enter a valid request'
            else:
                r = requests.post('https://www.dslchecker.bt.com/adsl/ADSLChecker.AddressOutput',
                                 data = {'buildingnumber': request.form['buildingnumber'],
                                       'postCode': request.form['PostCode']})
                result = r.text
                soup = BeautifulSoup(r.text, 'html.parser')
                soup.prettify()
                soup.find_all('span')
                result = {}
                result['VDSL Range A'] = {'Downstream': {'high':'', 'low':''},'Upstream': {'high':'', 'low':''}}
                result['WBC ADSL 2+'] = {'Downstream': '','Upstream': ''}
                result['WBC ADSL 2+ Annex M'] = {'Downstream': '','Upstream': ''}
		result['ADSL Max'] = {'Downstream': '','Upstream': ''}


		for span in soup.find_all('span'):
		    if "VDSL Range A (Clean)" in span:
			for index, child in enumerate(span.parent.parent.children):
			    #print index, child
			    if index == 3:
				result['VDSL Range A']['Downstream']['high'] = child.text
                                try:
                                    float(child.text)
                                    canFibre = True
                                except ValueError as verr:
                                    canFibre = False
			    if index == 5:
				result['VDSL Range A']['Downstream']['low'] = child.text
                                try:
                                    float(child.text)
                                    canFibre = True
                                except ValueError as verr:
                                    canFibre = False
			    if index == 7:
			       result['VDSL Range A']['Upstream']['high'] = child.text
			    if index == 9:
			       result['VDSL Range A']['Upstream']['low'] = child.text

	            if "WBC ADSL 2+" in span:
			for index, child in enumerate(span.parent.parent.children):
			    print index, child
			    if index == 3:
				result['WBC ADSL 2+']['Downstream'] = child.text.replace('Up to ','')
                                try:
                                    float(child.text.replace('Up to ',''))
                                    canADSL = True
                                except ValueError as verr:
                                    canADSL = False
			    if index == 5:
				result['WBC ADSL 2+']['Upstream'] = child.text.replace('Up to ','')
				if result['WBC ADSL 2+']['Upstream'].find("--") != -1:
                    			result['WBC ADSL 2+']['Upstream'] = ""

		    if "WBC ADSL 2+ Annex M" in span:
			for index, child in enumerate(span.parent.parent.children):
			    print index, child
			    if index == 3:
				result['WBC ADSL 2+ Annex M']['Downstream'] = child.text.replace('Up to ','')
                                try:
                                    float(child.text.replace('Up to ',''))
                                    canADSL = True
                                except ValueError as verr:
                                    canADSL = False
			    if index == 5:
				result['WBC ADSL 2+ Annex M']['Upstream'] = child.text.replace('Up to ','')
		                if result['WBC ADSL 2+ Annex M']['Upstream'].find("--") != -1:
                    			result['WBC ADSL 2+ Annex M']['Upstream'] = ""

		    if "ADSL Max" in span:
                        for index, child in enumerate(span.parent.parent.children):
                            print index, child
                            if index == 3:
                                result['ADSL Max']['Downstream'] = child.text.replace('Up to ','')
                                try:
                                    float(child.text.replace('Up to ',''))
                                    canADSL = True
                                except ValueError as verr:
                                    canADSL = False
                            if index == 5:
                                result['ADSL Max']['Upstream'] = child.text.replace('Up to ','')
				if result['ADSL Max']['Upstream'].find("--") != -1:
                    			result['ADSL Max']['Upstream'] = ""

                try:
                    if 'nophone' in request.headers['Cookie']:
                        nophone=True
                except  KeyError:
                    pass
                uptoSpeedFibre = result['VDSL Range A']['Downstream']['high']
                uptoSpeedADSL = result['WBC ADSL 2+']['Downstream']

                fields = {'title':time.time(),
                      'field_building_number':request.form['buildingnumber'],
                      'field_postcode_availability':request.form['PostCode'],
                      'field_vdsl_a_clean_mbps_high_dl':result['VDSL Range A']['Downstream']['high'],
                      'field_vdsl_a_clean_mbps_low_dl':result['VDSL Range A']['Downstream']['low'],
                      'field_vdsl_a_clean_mbps_high_ul':result['VDSL Range A']['Upstream']['high'],
                      'field_vdsl_a_clean_mbps_low_ul': result['VDSL Range A']['Upstream']['low'],
                      'field_adsl_2_downstream': result['WBC ADSL 2+']['Downstream'],
                      'field_adsl_2_upstream': result['WBC ADSL 2+']['Upstream'],
                      'field_adsl_2_annex_m_downstream': result['WBC ADSL 2+ Annex M']['Downstream'],
                      'field_adsl_2_annex_m_upstream': result['WBC ADSL 2+ Annex M']['Upstream'],
                      'field_adsl_max_downstream': result['ADSL Max']['Downstream'],
                      'field_adsl_max_upstream': result['ADSL Max']['Upstream']}
                Rest.post(entity='broadband_availability_lookup', fields=fields)

                return self.render_template('result.html', result=result, canADSL=canADSL, canFibre=canFibre, buildingnumber=buildingnumber, postCode=PostCode, now=prettyTime, nophone=nophone)
        return self.render_template('start.html', error=error, cheese=True, nophone=nophone)





    def insert_url(self, url):
        short_id = self.redis.get('reverse-url:' + url)
        if short_id is not None:
            return short_id
        url_num = self.redis.incr('last-url-id')
        short_id = base36_encode(url_num)
        self.redis.set('url-target:' + short_id, url)
        self.redis.set('reverse-url:' + url, short_id)
        return short_id

    def dispatch_request(self, request):
        adapter = self.url_map.bind_to_environ(request.environ)
        try:
            endpoint, values = adapter.match()
            return getattr(self, 'on_' + endpoint)(request, **values)
        except HTTPException, e:
            return e


    def wsgi_app(self, environ, start_response):
        request = Request(environ)
        response = self.dispatch_request(request)
        sid = request.cookies.get('karma_cookie')
        if sid is None:
            request.session = self.session_store.new()
        else:
            request.session = self.session_store.get(sid)
        try:
            self.session_store.save(request.session)
            response.set_cookie('karma_cookie', request.session.sid)
        except AttributeError as e:
            pass

        return response(environ, start_response)

    def __call__(self, environ, start_response):
        return self.wsgi_app(environ, start_response)

def create_app(with_static=True):
    app = Shortly({
    })
    if with_static:
        app.wsgi_app = SharedDataMiddleware(app.wsgi_app, {
            '/static': os.path.join(os.path.dirname(__file__), 'static')
        })
    return app

def is_valid_lookup(form):
    return True

def base36_encode(number):
    assert number >= 0, 'positive integer required'
    if number == 0:
        return '0'
    base36 = []
    while number != 0:
        number, i = divmod(number, 36)
        base36.append('0123456789abcdefghijklmnopqrstuvwxyz'[i])
    return ''.join(reversed(base36))

def source(script, update=1):
    pipe = Popen(". %s; env" % script, stdout=PIPE, shell=True)
    data = pipe.communicate()[0]

    env = dict((line.split("=", 1) for line in data.splitlines()))
    if update:
        environ.update(env)

    return env

if __name__ == '__main__':
    from werkzeug.serving import run_simple
    app = create_app()
    run_simple('0.0.0.0', 5000, app, use_debugger=False, use_reloader=True, ssl_context='adhoc')


application = create_app()
