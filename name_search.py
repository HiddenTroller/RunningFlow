"""Bounded product-name recovery. Similarity suggests candidates, never equivalence."""
import re
from difflib import SequenceMatcher
from mfds_client import ServiceError


def key(value):
    return re.sub(r'[^가-힣a-z0-9]', '', str(value).lower())


def search_variants(name):
    compact = re.sub(r'\s+|[®™]', '', name)
    compact = re.sub(r'\([^()]*\)', '', compact)
    brand = re.split(r'\d', compact, maxsplit=1)[0]
    brand = re.sub(r'(?:밀리그램|마이크로그램|서방정|연질캡슐|캡슐|내복액|정|액)$', '', brand)
    choices = [compact, brand]
    if len(key(brand)) >= 4:
        choices.append(brand[:3])
    result=[]
    for value in choices:
        if len(key(value)) >= 2 and value != name and value not in result:
            result.append(value)
    return result[:3]


def similar_search(client, name):
    items={}; queries=[]; truncated=False; source=''
    for query in search_variants(name):
        queries.append(query)
        try:
            found=client.search(query,1,page_size=30)
        except ServiceError:
            continue
        source=found.get('source',source)
        truncated |= found.get('total',0) > len(found.get('items',[]))
        for item in found.get('items',[]):
            code=str(item.get('ITEM_SEQ',''))
            title=str(item.get('ITEM_NAME','')).split('(')[0]
            score=SequenceMatcher(None,key(name),key(title),autojunk=False).ratio()
            brand=key(query)
            if code and score >= 0.5 and (len(brand)>=3 or score>=0.7):
                if code not in items or score > items[code][0]: items[code]=(score,item)
        if items: break
    ranked=sorted(items.values(),key=lambda pair:(-pair[0],str(pair[1].get('ITEM_SEQ',''))))
    return {'items':[item for _,item in ranked[:5]],'total':len(ranked),
            'source':source,'similarity':{str(item['ITEM_SEQ']):round(score,3) for score,item in ranked[:5]},
            'queries':queries,'truncated':truncated or len(ranked)>5}
