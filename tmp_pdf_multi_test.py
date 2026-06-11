from reportlab.pdfgen import canvas
from reportlab.lib import colors
from io import BytesIO

class NumberedCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        self._saved_page_states = []
        super().__init__(*args, **kwargs)

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        page_count = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_number(page_count)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_page_number(self, page_count):
        width, _height = self._pagesize
        self.setFont('Helvetica', 8)
        self.setFillColor(colors.HexColor('#6b7280'))
        self.drawCentredString(width / 2, 18, f'Page {self._pageNumber} of {page_count}')

buf = BytesIO()
cnv = NumberedCanvas(buf)
cnv.drawString(100, 750, 'Page one')
cnv.showPage()
cnv.drawString(100, 750, 'Page two')
cnv.save()
pdf = buf.getvalue()
print('page markers', pdf.count(b'/Type /Page'))
with open('f:/deployed/bsbcs_live/bsbcs_cms_live/tmp_pdf_multi_output.pdf', 'wb') as f:
    f.write(pdf)
