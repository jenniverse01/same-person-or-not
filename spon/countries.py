"""
countries.py - a small, hand-written country dictionary (standard library only).

Why: the data writes the same country in many ways: "United Kingdom", "GB",
"British", "UK". To compare countries we turn every spelling into ONE canonical
name, e.g. canonical_country("GB") -> "United Kingdom".

Each line below is:  Canonical name | 2-letter code | other spellings and nationality words
Territories (Puerto Rico, Jersey, Macao ...) are kept as their own country, as POLICY.md says.
"""
import re
import unicodedata

_TABLE = """
Afghanistan|AF|Afghan
Albania|AL|Albanian
Algeria|DZ|Algerian
Andorra|AD|Andorran
Angola|AO|Angolan
Argentina|AR|Argentine,Argentinian
Armenia|AM|Armenian
Australia|AU|Australian
Austria|AT|Austrian
Azerbaijan|AZ|Azerbaijani
Bahamas|BS|Bahamian,The Bahamas
Bahrain|BH|Bahraini
Bangladesh|BD|Bangladeshi
Barbados|BB|Barbadian
Belarus|BY|Belarusian
Belgium|BE|Belgian
Belize|BZ|Belizean
Benin|BJ|Beninese
Bermuda|BM|Bermudian
Bhutan|BT|Bhutanese
Bolivia|BO|Bolivian
Bosnia and Herzegovina|BA|Bosnian,Bosnia
Botswana|BW|Motswana,Batswana
Brazil|BR|Brazilian,Brasil
British Virgin Islands|VG|Virgin Islands British
Brunei|BN|Bruneian
Bulgaria|BG|Bulgarian
Burkina Faso|BF|Burkinabe
Burundi|BI|Burundian
Cambodia|KH|Cambodian
Cameroon|CM|Cameroonian
Canada|CA|Canadian
Cape Verde|CV|Cabo Verde,Cape Verdean
Cayman Islands|KY|Caymanian
Central African Republic|CF|
Chad|TD|Chadian
Chile|CL|Chilean
China|CN|Chinese,People's Republic of China
Colombia|CO|Colombian
Comoros|KM|Comorian
Congo|CG|Republic of the Congo,Congolese
Democratic Republic of the Congo|CD|DR Congo,DRC,Congo Kinshasa
Costa Rica|CR|Costa Rican
Cote d'Ivoire|CI|Ivory Coast,Ivorian
Croatia|HR|Croatian
Cuba|CU|Cuban
Curacao|CW|
Cyprus|CY|Cypriot
Czech Republic|CZ|Czechia,Czech
Denmark|DK|Danish
Djibouti|DJ|
Dominica|DM|
Dominican Republic|DO|Dominican
Ecuador|EC|Ecuadorian,Ecuadorean
Egypt|EG|Egyptian
El Salvador|SV|Salvadoran
Equatorial Guinea|GQ|
Eritrea|ER|Eritrean
Estonia|EE|Estonian
Eswatini|SZ|Swaziland
Ethiopia|ET|Ethiopian
Fiji|FJ|Fijian
Finland|FI|Finnish
France|FR|French
Gabon|GA|Gabonese
Gambia|GM|Gambian,The Gambia
Georgia|GE|Georgian
Germany|DE|German,Deutschland
Ghana|GH|Ghanaian
Gibraltar|GI|
Greece|GR|Greek
Grenada|GD|
Guam|GU|
Guatemala|GT|Guatemalan
Guernsey|GG|
Guinea|GN|Guinean
Guinea-Bissau|GW|
Guyana|GY|Guyanese
Haiti|HT|Haitian
Honduras|HN|Honduran
Hong Kong|HK|Hong Kong SAR,Hong Kong Special Administrative Region of China
Hungary|HU|Hungarian
Iceland|IS|Icelandic
India|IN|Indian
Indonesia|ID|Indonesian
Iran|IR|Iranian,Islamic Republic of Iran
Iraq|IQ|Iraqi
Ireland|IE|Irish,Republic of Ireland
Isle of Man|IM|
Israel|IL|Israeli
Italy|IT|Italian
Jamaica|JM|Jamaican
Japan|JP|Japanese
Jersey|JE|
Jordan|JO|Jordanian
Kazakhstan|KZ|Kazakh,Kazakhstani
Kenya|KE|Kenyan
Kosovo|XK|Kosovar
Kuwait|KW|Kuwaiti
Kyrgyzstan|KG|Kyrgyz
Laos|LA|Lao,Laotian
Latvia|LV|Latvian
Lebanon|LB|Lebanese
Lesotho|LS|
Liberia|LR|Liberian
Libya|LY|Libyan
Liechtenstein|LI|
Lithuania|LT|Lithuanian
Luxembourg|LU|Luxembourgish
Macao|MO|Macau,Macao Special Administrative Region of China,Macau SAR
Madagascar|MG|Malagasy
Malawi|MW|Malawian
Malaysia|MY|Malaysian
Maldives|MV|Maldivian
Mali|ML|Malian
Malta|MT|Maltese
Marshall Islands|MH|
Mauritania|MR|Mauritanian
Mauritius|MU|Mauritian
Mexico|MX|Mexican
Moldova|MD|Moldovan,Republic of Moldova
Monaco|MC|Monegasque
Mongolia|MN|Mongolian
Montenegro|ME|Montenegrin
Morocco|MA|Moroccan
Mozambique|MZ|Mozambican
Myanmar|MM|Burma,Burmese
Namibia|NA|Namibian
Nepal|NP|Nepali,Nepalese
Netherlands|NL|Dutch,Holland,The Netherlands
New Zealand|NZ|New Zealander
Nicaragua|NI|Nicaraguan
Niger|NE|Nigerien
Nigeria|NG|Nigerian
North Korea|KP|Democratic People's Republic of Korea,DPRK,North Korean
North Macedonia|MK|Macedonia,Macedonian
Northern Mariana Islands|MP|
Norway|NO|Norwegian
Oman|OM|Omani
Pakistan|PK|Pakistani
Palestine|PS|Palestina,Palestinian,State of Palestine
Panama|PA|Panamanian
Papua New Guinea|PG|
Paraguay|PY|Paraguayan
Peru|PE|Peruvian
Philippines|PH|Filipino,Philippine
Poland|PL|Polish
Portugal|PT|Portuguese
Puerto Rico|PR|Puerto Rican
Qatar|QA|Qatari
Romania|RO|Romanian
Russia|RU|Russian,Russian Federation
Rwanda|RW|Rwandan
Saudi Arabia|SA|Saudi
Senegal|SN|Senegalese
Serbia|RS|Serbian
Seychelles|SC|
Sierra Leone|SL|Sierra Leonean
Singapore|SG|Singaporean
Slovakia|SK|Slovak
Slovenia|SI|Slovenian,Slovene
Somalia|SO|Somali
South Africa|ZA|South African
South Korea|KR|Republic of Korea,Korea,South Korean
South Sudan|SS|
Spain|ES|Spanish,Espana
Sri Lanka|LK|Sri Lankan
Sudan|SD|Sudanese
Suriname|SR|
Sweden|SE|Swedish
Switzerland|CH|Swiss
Syria|SY|Syrian,Syrian Arab Republic
Taiwan|TW|Taiwanese
Tajikistan|TJ|Tajik
Tanzania|TZ|Tanzanian
Thailand|TH|Thai
Togo|TG|Togolese
Trinidad and Tobago|TT|Trinidadian
Tunisia|TN|Tunisian
Turkey|TR|Turkish,Turkiye
Turkmenistan|TM|Turkmen
Uganda|UG|Ugandan
Ukraine|UA|Ukrainian
United Arab Emirates|AE|UAE,Emirati
United Kingdom|GB|UK,British,Great Britain,England,Scotland,Wales,Northern Ireland
United States|US|USA,American,United States of America,U.S.
Uruguay|UY|Uruguayan
Uzbekistan|UZ|Uzbek
Venezuela|VE|Venezuelan
Vietnam|VN|Vietnamese,Viet Nam
Yemen|YE|Yemeni
Zambia|ZM|Zambian
Zimbabwe|ZW|Zimbabwean
"""

# Words that look like places but are NOT countries (POLICY.md principle 5).
NOT_COUNTRIES = {"international", "europe", "global", "worldwide"}


def _key(text):
    """Lowercase, strip accents and punctuation so 'Côte d'Ivoire' == 'cote divoire'."""
    text = unicodedata.normalize("NFKD", str(text))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace("'", "").replace("\u2019", "")
    text = re.sub(r"[^a-z0-9 ]", " ", text)          # "Germany-issued" -> "germany issued"
    return re.sub(r"\s+", " ", text).strip()


_LOOKUP = {}      # spelling key -> canonical name
_CODES = {}       # "GB" -> "United Kingdom"
CANONICAL = []
for _line in _TABLE.strip().splitlines():
    _name, _code, _others = _line.split("|")
    CANONICAL.append(_name)
    _CODES[_code] = _name
    _LOOKUP[_key(_name)] = _name
    for _o in filter(None, _others.split(",")):
        _LOOKUP[_key(_o)] = _name


def canonical_country(text):
    """Turn any country spelling, code or nationality word into the canonical name.
    Returns None when the text is empty, not a country, or 'International'/'Europe'."""
    if text is None:
        return None
    raw = str(text).strip()
    # drop tags like "Brazil [PEP]" and keep the last comma part of an address
    raw = re.sub(r"\[.*?\]", "", raw).strip()
    if "," in raw:
        raw = raw.split(",")[-1].strip()
    if not raw:
        return None
    if raw.upper() in _CODES and len(raw) == 2 and raw.isupper():
        return _CODES[raw.upper()]
    k = _key(raw)
    if k in NOT_COUNTRIES:
        return None
    return _LOOKUP.get(k)


# Pre-built regex to FIND country names / nationality words inside free text (notes, snippets).
_FIND_KEYS = sorted((k for k in _LOOKUP if len(k) > 3 or k in ("uk", "usa", "uae")), key=len, reverse=True)
_FIND_RE = re.compile(r"\b(" + "|".join(re.escape(k) for k in _FIND_KEYS) + r")\b")


def countries_in_text(text):
    """Return every canonical country mentioned in a sentence (in order, no repeats)."""
    if not text:
        return []
    found = []
    for m in _FIND_RE.finditer(_key(text)):
        c = _LOOKUP[m.group(1)]
        if c not in found:
            found.append(c)
    return found
