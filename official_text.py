"""Render official dosage XML as inert, readable text, preserving tables."""
from html.parser import HTMLParser
import re
import xml.etree.ElementTree as ET

class PlainText(HTMLParser):
    def __init__(self):super().__init__(convert_charrefs=True);self.parts=[];self.skip=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'):self.skip+=1
        if not self.skip and tag in ('p','tr','br','li','div'):self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style'):self.skip=max(0,self.skip-1)
        elif not self.skip and tag in ('td','th'):self.parts.append(' | ')
    def handle_data(self,data):
        if not self.skip:self.parts.append(data)

def dosage_text(value):
    if not isinstance(value,str) or not value.strip():return ''
    try:
        root=ET.fromstring(value)
        fragments=[''.join(e.itertext()) for e in root.iter('PARAGRAPH')]
        raw='\n'.join(fragments) if fragments else ''.join(root.itertext())
    except ET.ParseError:raw=value
    parser=PlainText();parser.feed(raw);parser.close()
    return '\n'.join(re.sub(r'[ \t\r]+',' ',line).strip(' |') for line in ''.join(parser.parts).split('\n') if line.strip(' |\r\t '))
