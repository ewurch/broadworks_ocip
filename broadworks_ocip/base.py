import re
from collections import namedtuple

from classforge import Class
from classforge import Field
from lxml import etree


class ElementInfo(
    namedtuple(
        "ElementInfo",
        ["name", "xmlname", "type", "is_complex", "is_required", "is_table"],
    ),
):
    pass


class OCIType(Class):
    DEFAULT_NSMAP = {None: "", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    DOCUMENT_NSMAP = {None: "C", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}

    def _etree_sub_components(self, element):
        for sub_element in self.ELEMENTS:
            value = getattr(self, sub_element.name)
            if value is None:
                if sub_element.is_required:
                    etree.SubElement(
                        element,
                        sub_element.xmlname,
                        {"{http://www.w3.org/2001/XMLSchema-instance}nil": "true"},
                        nsmap=self.DEFAULT_NSMAP,
                    )
            elif sub_element.is_complex:
                sub_element.append(value._etree_components(sub_element.xmlname))
            else:
                elem = etree.SubElement(
                    element, sub_element.xmlname, nsmap=self.DEFAULT_NSMAP,
                )
                elem.text = value
        return element

    def _etree_components(self, name=None):
        if name is None:
            name = self.__class__.__name__
        element = etree.Element(name, nsmap=self.DEFAULT_NSMAP)
        return self._etree_sub_components(element)

    @classmethod
    def _column_header_snake_case(cls, header):
        return re.sub("[ _]+", r"_", header).lower()

    @classmethod
    def _decode_table(cls, element):
        typename = element.tag
        results = []
        columns = [
            cls._column_header_snake_case(b.text)
            for b in element.iterfind("colHeading")
        ]
        type = namedtuple(typename, columns)
        for row in element.iterfind("row"):
            rowdata = [b.text for b in row.iterfind("col")]
            rowobj = type(*rowdata)
            results.append(rowobj)
        return results

    @classmethod
    def _build_from_etree(cls, element):
        initialiser = {}
        for elem in cls.ELEMENTS:
            node = element.find(elem.xmlname)
            if node is not None:
                if elem.is_table:
                    initialiser[elem.name] = cls._decode_table(node)
                elif elem.is_complex:
                    initialiser[elem.name] = elem.type._build_from_etree(node)
                else:
                    initialiser[elem.name] = elem.type(node.text)
            # else...
            # I am inclined to thow an error here - at least after checking if
            # the thing is require, but the class builder should do that so lets
            # let it do its thing
        # now have a dict with all the bits in it.
        # use that to build a new object
        return cls(**initialiser)


class OCIRequest(OCIType):
    def _build_xml(self, session="test-session-123"):
        # document root element
        root = etree.Element(
            "{C}BroadsoftDocument", {"protocol": "OCI"}, nsmap=self.DOCUMENT_NSMAP,
        )
        #
        # add the session
        sess = etree.SubElement(root, "sessionId", nsmap=self.DEFAULT_NSMAP)
        sess.text = session
        #
        # and the command
        element = etree.SubElement(
            root,
            "command",
            {
                "{http://www.w3.org/2001/XMLSchema-instance}type": self.__class__.__name__,
            },
            nsmap=self.DEFAULT_NSMAP,
        )
        self._etree_sub_components(element)  # attach parameters etc
        #
        # wrap a tree around it
        tree = etree.ElementTree(root)
        return etree.tostring(
            tree,
            xml_declaration=True,
            encoding="ISO-8859-1",
            # standalone=False,
            # pretty_print=True,
        )


class OCIResponse(OCIType):
    pass


class SuccessResponse(OCIResponse):
    """
    The SuccessResponse is concrete response sent whenever a transaction is successful
    and does not return any data.
    """

    ELEMENTS = tuple()  # type: ignore # type: Tuple[Tuple]


class ErrorResponse(OCIResponse):
    """
    The ErrorResponse is concrete response sent whenever a transaction fails and does not return any data.
    """

    ELEMENTS = (
        ElementInfo("error_code", "errorCode", int, False, False, False),
        ElementInfo("summary", "summary", str, False, True, False),
        ElementInfo("summary_english", "summaryEnglish", str, False, True, False),
        ElementInfo("detail", "detail", str, False, False, False),
        ElementInfo("type", "type", str, False, True, False),
    )
    error_code = Field(type=int, required=False)
    summary = Field(type=str, required=True)
    summary_english = Field(type=str, required=True)
    detail = Field(type=str, required=False)
    type = Field(type=str, required=True)

    def on_init(self):
        raise Exception()


# end
