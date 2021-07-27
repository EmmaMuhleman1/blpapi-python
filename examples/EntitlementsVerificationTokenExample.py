# EntitlementsVerificationTokenExample.py
from __future__ import print_function
from __future__ import absolute_import

from optparse import OptionParser

import os
import platform as plat
import sys
if sys.version_info >= (3, 8) and plat.system().lower() == "windows":
    # pylint: disable=no-member
    with os.add_dll_directory(os.getenv('BLPAPI_LIBDIR')):
        import blpapi
else:
    import blpapi

SECURITY_DATA = blpapi.Name("securityData")
SECURITY = blpapi.Name("security")
EID_DATA = blpapi.Name("eidData")
AUTHORIZATION_SUCCESS = blpapi.Name("AuthorizationSuccess")

REFRENCEDATA_REQUEST = "ReferenceDataRequest"
APIAUTH_SVC = "//blp/apiauth"
REFDATA_SVC = "//blp/refdata"


def printEvent(event):
    for msg in event:
        corrId = msg.correlationIds()[0]
        if corrId.value():
            print("Correlator:", corrId.value())
        print(msg)


class SessionEventHandler(object):
    def __init__(self, identities, tokens):
        self.identities = identities
        self.tokens = tokens

    def printFailedEntitlements(self, listOfFailedEIDs):
        print(listOfFailedEIDs)

    def distributeMessage(self, msg):
        service = msg.service()
        securities = msg.getElement(SECURITY_DATA)
        numSecurities = securities.numValues()
        print("Processing %s securities" % numSecurities)
        for i in range(numSecurities):
            security = securities.getValueAsElement(i)
            ticker = security.getElementAsString(SECURITY)
            entitlements = None
            if security.hasElement(EID_DATA):
                entitlements = security.getElement(EID_DATA)
            if (entitlements is not None and
                    entitlements.isValid() and
                    entitlements.numValues() > 0):
                for j, identity in enumerate(self.identities):
                    if identity.hasEntitlements(service, entitlements):
                        print("User: %s is entitled to get data for: %s" % \
                            (j + 1, ticker))
                    else:
                        print("User: %s is NOT entitled to get data for: %s " \
                            "- Failed eids:" % (j + 1, ticker))
                        self.printFailedEntitlements(
                            identity.getFailedEntitlements(service,
                                                           entitlements)[1])
            else:
                for token in self.tokens:
                    print("User: %s is entitled to get data for: %s" % \
                        (token, ticker))
                    # Now Distribute message to the user.

    def processResponseEvent(self, event):
        for msg in event:
            if msg.hasElement("RESPONSE_ERROR") or msg.hasElement("responseError"):
                print(msg)
                continue
            self.distributeMessage(msg)

    def processEvent(self, event, _session):
        if (event.eventType() == blpapi.Event.SESSION_STATUS or
                event.eventType() == blpapi.Event.SERVICE_STATUS or
                event.eventType() == blpapi.Event.REQUEST_STATUS or
                event.eventType() == blpapi.Event.AUTHORIZATION_STATUS):
            printEvent(event)
        elif (event.eventType() == blpapi.Event.RESPONSE or
                event.eventType() == blpapi.Event.PARTIAL_RESPONSE):
            try:
                self.processResponseEvent(event)
            except blpapi.Exception as e:
                print("Library Exception !!! %s" % e.description())
        return True


def parseCmdLine():
    # Parse command-line parameters
    parser = OptionParser(
        description="Entitlements verification token example")
    parser.add_option("-s",
                      dest="securities",
                      help="security (default: IBM US Equity)",
                      metavar="security",
                      action="append",
                      default=[])
    parser.add_option("-t",
                      "--token",
                      dest="tokens",
                      help="token value returned in generateToken response",
                      metavar="token",
                      action="append",
                      default=[])
    parser.add_option("-a",
                      "--ip",
                      dest="host",
                      help="server name or IP (default: %default)",
                      metavar="ipAddress",
                      default="localhost")
    parser.add_option("-p",
                      dest="port",
                      type="int",
                      help="server port (default: %default)",
                      metavar="tcpPort",
                      default=8194)

    options,_ = parser.parse_args()

    if not options.securities:
        options.securities = ["MSFT US Equity"]

    return options


def authorizeUsers(session, tokens, identities):
    authService = session.getService(APIAUTH_SVC)
    is_any_user_authorized = False

    # Authorize each of the users
    for index, token in enumerate(tokens):
        identity = session.createIdentity()
        identities.append(identity)
        authRequest = authService.createAuthorizationRequest()
        authRequest.set("token", token)
        correlator = blpapi.CorrelationId(token)
        eventQueue = blpapi.EventQueue()
        session.sendAuthorizationRequest(authRequest,
                                           identity,
                                           correlator,
                                           eventQueue)
        event = eventQueue.nextEvent()
        if (event.eventType() == blpapi.Event.RESPONSE or
                event.eventType() == blpapi.Event.REQUEST_STATUS):
            for msg in event:
                if msg.messageType() == AUTHORIZATION_SUCCESS:
                    print("User %s authorization success" % (index + 1))
                    is_any_user_authorized = True
                else:
                    print("User %s authorization failed" % (index + 1))
                    printEvent(event)
    return is_any_user_authorized


def sendRefDataRequest(session, securities):
    refDataService = session.getService(REFDATA_SVC)
    request = refDataService.createRequest(REFRENCEDATA_REQUEST)

    # Add securities to the request
    securitiesEl = request.getElement("securities")
    for security in securities:
        securitiesEl.appendValue(security)

    # Add fields to the request
    fields = request.getElement("fields")
    fields.appendValue("PX_LAST")
    fields.appendValue("DS002")

    request.set("returnEids", True)

    # Send the request using the server's credentials
    print("Sending RefDataRequest using server credentials...")
    session.sendRequest(request)


def main():
    options = parseCmdLine()

    # Create SessionOptions object and populate it with data
    sessionOptions = blpapi.SessionOptions()
    sessionOptions.setServerHost(options.host)
    sessionOptions.setServerPort(options.port)

    securities = options.securities
    if not options.tokens:
        print("No tokens were specified")
        return

    tokens = options.tokens
    print(tokens)

    identities = []

    # Create Session object and connect to Bloomberg services
    print("Connecting to %s:%s" % (options.host, options.port))
    eventHandler = SessionEventHandler(identities, tokens)
    session = blpapi.Session(sessionOptions, eventHandler.processEvent)
    if not session.start():
        print("Failed to start session.")
        return

    # Open authorization service
    if not session.openService("//blp/apiauth"):
        print("Failed to open //blp/apiauth")
        return

    # Open reference data service
    if not session.openService("//blp/refdata"):
        print("Failed to open //blp/refdata")
        return

    # Authorize all the users that are interested in receiving data
    if authorizeUsers(session, tokens, identities):
        # Make the various requests that we need to make
        sendRefDataRequest(session, securities)

    try:
        # Wait for enter key to exit application
        print("Press ENTER to quit")
        input()
    finally:
        # Stop the session
        session.stop()

if __name__ == "__main__":
    print("EntitlementsVerificationTokenExample")
    try:
        main()
    except KeyboardInterrupt:
        print("Ctrl+C pressed. Stopping...")

__copyright__ = """
Copyright 2012. Bloomberg Finance L.P.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to
deal in the Software without restriction, including without limitation the
rights to use, copy, modify, merge, publish, distribute, sublicense, and/or
sell copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:  The above
copyright notice and this permission notice shall be included in all copies
or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS
IN THE SOFTWARE.
"""
